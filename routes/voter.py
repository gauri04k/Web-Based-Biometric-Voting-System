

import base64
import cv2
import numpy as np
from flask import Blueprint, request, render_template, redirect, url_for, flash, session, jsonify
from deepface import DeepFace
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
from datetime import datetime

voter_bp = Blueprint("voter_bp", __name__)

# MongoDB connection
client = MongoClient("mongodb://localhost:27017/")
db = client["voting_system"]
voters_collection = db["voters"]
elections_collection = db["elections"]
votes_collection = db["votes"]

# Load Haar Cascade for face detection
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def decode_image(image_base64):
    """Convert Base64 image to OpenCV format"""
    try:
        image_data = base64.b64decode(image_base64.split(",")[1])
        np_arr = np.frombuffer(image_data, np.uint8)
        return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def detect_face(image):
    """Detect a face in an image"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    return faces[0] if len(faces) > 0 else None  # Return first detected face or None


@voter_bp.route("/", methods=["GET"])
def voter_home():
    return render_template("voter_home.html")


@voter_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        voter = voters_collection.find_one({"email": email})
        if not voter or not check_password_hash(voter["password"], password):
            flash("Invalid email or password!", "danger")
            return redirect(url_for("voter_bp.login"))

        session["voter_id"] = str(voter["_id"])
        session["voter_name"] = voter["name"]

        flash(f"Welcome, {voter['name']}!", "success")
        return redirect(url_for("voter_bp.dashboard"))  # Redirect to dashboard

    return render_template("voter_login.html")


@voter_bp.route("/login/face", methods=["POST"])
def face_login():
    try:
        data = request.get_json()
        face_data = data.get("face_data")

        if not face_data:
            return jsonify({"error": "Face data is required!"})

        face_img = decode_image(face_data)
        if face_img is None or detect_face(face_img) is None:
            return jsonify({"error": "No face detected! Please try again."})

        target_embedding = DeepFace.represent(face_img, model_name="Facenet")[0]["embedding"]

        # Compare with stored embeddings
        best_match = None
        best_distance = float("inf")

        for user in voters_collection.find():
            stored_embedding = np.array(user["face_embedding"])
            distance = np.linalg.norm(stored_embedding - np.array(target_embedding))

            if distance < best_distance and distance < 10:  # Lower distance means better match
                best_distance = distance
                best_match = user

        if best_match:
            session["voter_id"] = str(best_match["_id"])
            session["voter_name"] = best_match["name"]
            return jsonify({"message": f"Login successful! Welcome, {best_match['name']}.", "redirect": url_for("voter_bp.dashboard")})
        else:
            return jsonify({"error": "Face not recognized! Please try again."})

    except Exception as e:
        return jsonify({"error": str(e)})




@voter_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("voter_bp.voter_home"))



@voter_bp.route("/verify_face", methods=["POST"])
def verify_face():
    """Verify voter's face before allowing them to vote."""
    try:
        data = request.get_json()
        face_data = data.get("face_data")

        if not face_data:
            return jsonify({"success": False, "error": "Face data is required!"})

        face_img = decode_image(face_data)
        if face_img is None or detect_face(face_img) is None:
            return jsonify({"success": False, "error": "No face detected! Please try again."})

        target_embedding = DeepFace.represent(face_img, model_name="Facenet")[0]["embedding"]

        # Compare with stored voter embeddings
        voter_id = session.get("voter_id")
        if not voter_id:
            return jsonify({"success": False, "error": "User session expired! Please log in again."})

        voter = voters_collection.find_one({"_id": ObjectId(voter_id)})
        if not voter:
            return jsonify({"success": False, "error": "Voter not found!"})

        stored_embedding = np.array(voter["face_embedding"])
        distance = np.linalg.norm(stored_embedding - np.array(target_embedding))

        if distance < 10:  # Adjust the threshold if needed
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Face not recognized!"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@voter_bp.route('/vote/<election_id>', methods=['GET', 'POST'])
def vote(election_id):
    if "voter_id" not in session:
        flash("Please log in first.", "warning")
        return redirect(url_for("voter_bp.login"))

    voter_id = ObjectId(session["voter_id"])
    voter = voters_collection.find_one({"_id": voter_id})

    if not voter:
        flash("Voter not found!", "danger")
        return redirect(url_for("voter_bp.dashboard"))

    # Check if voter is verified
    if not voter.get("verified", False):
        flash("You are not verified to vote. Please contact the administrator.", "danger")
        return redirect(url_for("voter_bp.dashboard"))

    election = elections_collection.find_one({"_id": ObjectId(election_id)})
    if not election:
        flash("Election not found!", "danger")
        return redirect(url_for("voter_bp.dashboard"))

    candidates = election.get("candidates", [])

    if request.method == "POST":
        face_data = request.form.get("face_data")
        selected_candidate = request.form.get("candidate")

        if not face_data or not selected_candidate:
            flash("Please select a candidate and verify your face.", "danger")
            return redirect(url_for("voter_bp.vote", election_id=election_id))

        # Face recognition verification
        face_img = decode_image(face_data)
        if face_img is None or detect_face(face_img) is None:
            flash("No face detected! Please try again.", "danger")
            return redirect(url_for("voter_bp.vote", election_id=election_id))

        # Extract facial embeddings
        try:
            target_embedding = DeepFace.represent(face_img, model_name="Facenet")[0]["embedding"]
        except:
            flash("Face recognition failed! Try again.", "danger")
            return redirect(url_for("voter_bp.vote", election_id=election_id))

        # Compare with stored voter embedding
        stored_embedding = np.array(voter["face_embedding"])
        distance = np.linalg.norm(stored_embedding - np.array(target_embedding))

        if distance > 10:  # Adjust threshold if needed
            flash("Face does not match! Voting failed.", "danger")
            return redirect(url_for("voter_bp.vote", election_id=election_id))

        # Check if voter has already voted
        existing_vote = votes_collection.find_one({"voter_id": voter_id, "election_id": ObjectId(election_id)})
        if existing_vote:
            flash("You have already voted in this election!", "warning")
            return redirect(url_for("voter_bp.dashboard"))

        # Store vote in database
        vote_data = {
            "voter_id": voter_id,
            "election_id": ObjectId(election_id),
            "candidate": selected_candidate,
            "timestamp": datetime.now()
        }
        votes_collection.insert_one(vote_data)

        flash("Vote submitted successfully!", "success")
        return redirect(url_for("voter_bp.dashboard"))

    return render_template("vote.html", election=election, candidates=candidates)







   



from ast import literal_eval
@voter_bp.route("/election_results/<election_id>", methods=["GET"])
def voter_election_results(election_id):
    if "voter_id" not in session:
        flash("Please log in first.", "warning")
        return redirect(url_for("voter_bp.login"))

    voter_id = ObjectId(session["voter_id"])
    voter = voters_collection.find_one({"_id": voter_id})

    if not voter:
        flash("Voter not found!", "danger")
        return redirect(url_for("voter_bp.dashboard"))

    # Fetch the election
    election = elections_collection.find_one({"_id": ObjectId(election_id)})
    if not election:
        flash("Election not found!", "danger")
        return redirect(url_for("voter_bp.dashboard"))

    # Check if the voter's location matches the election's region
    if election.get("region") != voter.get("location"):
        flash("You are not eligible to view results for this election.", "danger")
        return redirect(url_for("voter_bp.dashboard"))

    # Fetch all votes for the election
    votes = list(votes_collection.find({"election_id": ObjectId(election_id)}))

    # Aggregate votes manually
    results = {}
    for vote in votes:
        # Parse the candidate string into a dictionary
        try:
            candidate = literal_eval(vote["candidate"])  # Convert string to dictionary
            candidate_key = (candidate["name"], candidate["party"])  # Use (name, party) as key
        except (ValueError, KeyError, SyntaxError):
            continue  # Skip invalid candidate data

        # Count votes for each candidate
        if candidate_key in results:
            results[candidate_key] += 1
        else:
            results[candidate_key] = 1

    # Convert results to a list of dictionaries for the template
    results_list = [
        {"name": key[0], "party": key[1], "votes": value}
        for key, value in results.items()
    ]

    # Sort results by vote count (descending)
    results_list.sort(key=lambda x: x["votes"], reverse=True)

    return render_template("voter_election_results.html", election=election, results=results_list)












import base64
import numpy as np
from flask import request, flash, redirect, url_for, render_template
from werkzeug.security import generate_password_hash
from deepface import DeepFace
import cv2
import json
from bson.binary import Binary

@voter_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = generate_password_hash(request.form.get("password"))
        location = request.form.get("location")  # Capture location
        face_data = request.form.get("face_data")
        Voter_Id = request.form.get("Voter_Id")
        Aadhar_Id = request.form.get("Aadhar_Id")
        Mobile_Num = request.form.get("Mobile_Num")
        DOB = request.form.get("DOB")

        print("Location received:", location)  # Debugging step

        if not face_data:
            flash("Please capture your face!", "danger")
            return redirect(url_for("voter_bp.register"))

        # Decode the base64 face data
        try:
            face_img_data = base64.b64decode(face_data.split(",")[1])  # Extracting actual image data
        except Exception as e:
            flash("Invalid image format! Try again.", "danger")
            return redirect(url_for("voter_bp.register"))

        # Convert to OpenCV format for face detection
        np_arr = np.frombuffer(face_img_data, np.uint8)
        face_img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if face_img is None or detect_face(face_img) is None:
            flash("No face detected! Please try again.", "danger")
            return redirect(url_for("voter_bp.register"))

        # Extract facial embeddings
        try:
            embedding = DeepFace.represent(face_img, model_name="Facenet")[0]["embedding"]
        except:
            flash("Face recognition failed! Try again.", "danger")
            return redirect(url_for("voter_bp.register"))

        # Save voter to database with binary image
        voter_data = {
            "name": name,
            "email": email,
            "password": password,
            "face_embedding": embedding,
            "location": location,  
            "Voter_Id": Voter_Id,
            "Aadhar_Id": Aadhar_Id,
            "Mobile_Num": Mobile_Num,
            "date": DOB,
            "verified": False,
            "face_image": Binary(face_img_data)  # Store image as binary in MongoDB
        }

        voters_collection.insert_one(voter_data)

        flash("Registration successful! You can now log in.", "success")
        return redirect(url_for("voter_bp.voter_home"))

    return render_template("voter_register.html")










import base64
from flask import session, flash, redirect, url_for, render_template
from bson.objectid import ObjectId
from datetime import datetime

@voter_bp.route("/dashboard", methods=["GET"])
def dashboard():
    if "voter_id" not in session:
        flash("Please log in first.", "warning")
        return redirect(url_for("voter_bp.login"))

    voter_id = ObjectId(session["voter_id"])
    current_time = datetime.now()

    # Fetch voter details including location, verification status, and face image
    voter = voters_collection.find_one({"_id": voter_id}, {"name": 1, "location": 1, "verified": 1, "face_image": 1})
    if not voter:
        flash("Voter not found!", "danger")
        return redirect(url_for("voter_bp.login"))

    voter_name = voter.get("name", "Voter")  # Default to "Voter" if name is missing
    voter_location = voter.get("location")  # Get the voter's location
    voter_verified = voter.get("verified", False)  # Get the voter's verification status
    face_image_data = voter.get("face_image")  # Retrieve binary image data

    if not voter_location:
        flash("Your location is not set. Please update your profile.", "warning")
        return redirect(url_for("voter_bp.voter_home"))

    # Convert binary image to Base64 for rendering in HTML
    face_image_base64 = None
    if face_image_data:
        face_image_base64 = base64.b64encode(face_image_data).decode("utf-8")

    # Fetch elections that match the voter's location
    ongoing_elections = list(elections_collection.find({
        "start_time": {"$lte": current_time},
        "end_time": {"$gte": current_time},
        "region": voter_location  # Filter by voter's location
    }))

    upcoming_elections = list(elections_collection.find({
        "start_time": {"$gt": current_time},
        "region": voter_location  # Filter by voter's location
    }))

    # Fetch voted elections
    voted_elections = votes_collection.find({"voter_id": voter_id})
    voted_election_ids = {str(vote["election_id"]) for vote in voted_elections}

    return render_template(
        "voter_dashboard.html",
        voter_name=voter_name,  
        voter=voter,  
        face_image=face_image_base64,  # Pass face image to template
        ongoing_elections=ongoing_elections,
        upcoming_elections=upcoming_elections,
        voted_election_ids=voted_election_ids
    )

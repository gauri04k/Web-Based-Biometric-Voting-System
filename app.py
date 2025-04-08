from flask import Flask, render_template
from db import mongo  # Import MongoDB instance from db.py
from routes.admin import admin_bp
from routes.voter import voter_bp

app = Flask(__name__)
app.config["MONGO_URI"] = "mongodb://localhost:27017/voting_system"
app.config["SECRET_KEY"] = "your_super_secret_key"

mongo.init_app(app)  # Initialize MongoDB with the Flask app

# Register Blueprints
app.register_blueprint(admin_bp, url_prefix="/admin")
app.register_blueprint(voter_bp, url_prefix="/voter")

@app.route("/")
def home():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)



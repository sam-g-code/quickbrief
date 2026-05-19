from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dataclasses import asdict
import os
import tempfile

import notams_parser
print("APP IMPORTING NOTAMS FROM:", notams_parser.__file__)

from parser import parse_briefing

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/api/briefing", methods=["POST"])
def briefing():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        file.save(tmp.name)
        pdf_path = tmp.name

    try:
        briefing_obj = parse_briefing(pdf_path)
        data = asdict(briefing_obj)
        return jsonify(data)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
from flask import Flask, request, jsonify

app = Flask(__name__)

# In a real application, this would be a database of customers.
# The key is the license key, the value could be an object with subscription status, expiry, etc.
VALID_LICENSES = {
    "YOUR_SUPER_SECRET_LICENSE_KEY": {"status": "active", "tier": "free"},
    "ANOTHER-EXPIRED-KEY-EXAMPLE": {"status": "lapsed"},
    "D1ZmwnrP91Lan-PLRQ7tBEYYYod7Eypos_KBKvwaHLg": {"status": "active", "tier": "paid"}
}


@app.route('/check_license', methods=['POST'])
def check_license():
    data = request.get_json()
    print("DEBUG: Received data:", data)
    if not data or 'license_key' not in data:
        print("DEBUG: Missing license_key in request data.")
        return jsonify({"error": "Missing license_key"}), 400

    license_key = data['license_key']
    print("DEBUG: license_key from request:", repr(license_key))
    print("DEBUG: VALID_LICENSES keys:", list(VALID_LICENSES.keys()))
    license_info = VALID_LICENSES.get(license_key)

    if license_info:
        print("DEBUG: License key matched. Returning:", license_info)
        return jsonify(license_info)
    else:
        print("DEBUG: License key not found. Returning 404.")
        return jsonify({"status": "invalid"}), 404


if __name__ == '__main__':
    # For production, use a proper WSGI server like Gunicorn or Waitress.
    app.run(debug=True, port=5000)

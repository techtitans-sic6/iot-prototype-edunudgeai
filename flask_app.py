from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime
import os
import threading
import time
import logging
from logging.handlers import RotatingFileHandler

# Konfigurasi Aplikasi
app = Flask(__name__)
CORS(app)

# Konfigurasi MongoDB
MONGO_URI = "mongodb://tech_titans:edunudgeai@localhost:27017/edunudge_db?authSource=admin"
client = MongoClient(MONGO_URI)
db = client['edunudge_db']
sensor_collection = db['sensor_data']

# Konfigurasi Logging
log_handler = RotatingFileHandler('flask.log', maxBytes=10000, backupCount=3)
log_handler.setFormatter(logging.Formatter(
    '[%(asctime)s] %(levelname)s: %(message)s'
))
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)

# API Key Validation
VALID_API_KEYS = {"EduNudgeAI": "sensor_device"}

def validate_api_key(headers):
    api_key = headers.get('X-API-KEY')
    return api_key in VALID_API_KEYS

def initialize_database():
    """Function to initialize database indexes and collections"""
    try:
        # Cek apakah koleksi sudah ada
        if 'sensor_data' not in db.list_collection_names():
            db.create_collection('sensor_data')
            app.logger.info("Created sensor_data collection")
        
        # Buat index jika belum ada
        if "timestamp_-1" not in sensor_collection.index_information():
            sensor_collection.create_index([("timestamp", -1)], name="timestamp_-1")
            app.logger.info("Created timestamp index")
    except Exception as e:
        app.logger.error(f"Error initializing database: {str(e)}")
        raise e

@app.route('/api/sensor', methods=['POST'])
def receive_sensor_data():
    if not validate_api_key(request.headers):
        app.logger.warning("Unauthorized access attempt")
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    try:
        data = request.json
        required_fields = ['temp', 'hum', 'light', 'motion', 'sound']
        
        if not all(field in data for field in required_fields):
            return jsonify({"status": "error", "message": "Missing fields"}), 400
        
        # Tambahkan metadata
        sensor_data = {
            **data,
            "timestamp": datetime.now(),
            "device_type": "ESP32-Sensor"
        }
        
        # Simpan ke MongoDB
        result = sensor_collection.insert_one(sensor_data)
        
        app.logger.info(f"Data saved: {result.inserted_id}")
        return jsonify({
            "status": "success",
            "message": "Data saved",
            "id": str(result.inserted_id)
        }), 201
        
    except Exception as e:
        app.logger.error(f"Error saving data: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/sensor/latest', methods=['GET'])
def get_latest_data():
    try:
        # Ambil 10 data terbaru
        data = list(sensor_collection.find().sort("timestamp", -1).limit(10))
        
        # Format data untuk response
        formatted_data = []
        for item in data:
            item['_id'] = str(item['_id'])
            item['timestamp'] = item['timestamp'].isoformat()
            formatted_data.append(item)
        
        return jsonify({
            "status": "success",
            "count": len(formatted_data),
            "data": formatted_data
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/sensor/aggregate', methods=['GET'])
def get_aggregated_data():
    try:
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "avgTemp": {"$avg": "$temp"},
                    "avgHum": {"$avg": "$hum"},
                    "avgLight": {"$avg": "$light"},
                    "avgSound": {"$avg": "$sound"},
                    "motionCount": {"$sum": "$motion"}
                }
            }
        ]
        
        result = list(sensor_collection.aggregate(pipeline))[0]
        del result['_id']
        
        return jsonify({
            "status": "success",
            "data": result
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # Initialize database before first request
    try:
        initialize_database()
    except Exception as e:
        app.logger.error(f"Failed to initialize database: {str(e)}")
        raise e
    
    # Jalankan server
    app.run(host='0.0.0.0', port=5001, debug=True)

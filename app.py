import os
import random
import shutil
import sqlite3
from datetime import datetime
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template, send_from_directory, request, redirect, url_for, flash, session, g
import requests
import json
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Thread pool for background tasks
thread_pool = ThreadPoolExecutor(max_workers=4)

# Cache for source information results
source_cache = {}

# Secret key for session management
app.config['SECRET_KEY'] = 'super_secret_key_for_app'

# Replace with your actual SauceNao API key
SAUCENAO_API_KEY = os.environ.get('SAUCENAO_API_KEY', 'APIKEYHERE')

# SauceNao API URL
SAUCENAO_API_URL = 'https://saucenao.com/search.php'

# Data directory paths
DATA_DIR = 'data'
IMAGES_FOLDER_INTERNAL = os.path.join(DATA_DIR, 'images')
PENDING_UPLOADS_FOLDER = os.path.join(DATA_DIR, 'pending_images')
DATABASE_PATH = os.path.join(DATA_DIR, 'sqlite', 'site.db')
MOTD_PATH = os.path.join(DATA_DIR, 'motd.txt')

# File upload configuration
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 Megabytes limit for file uploads

# Ensure data directories exist
os.makedirs(IMAGES_FOLDER_INTERNAL, exist_ok=True)
os.makedirs(PENDING_UPLOADS_FOLDER, exist_ok=True)
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

# --- Database Helper Functions ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE_PATH)
        db.row_factory = sqlite3.Row
    return db

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def insert_db(query, args=()):
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    last_id = cur.lastrowid
    cur.close()
    return last_id

def update_db(query, args=()):
    db = get_db()
    db.execute(query, args)
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- Database Schema ---
def create_tables():
    db = get_db()
    
    # Create users table
    db.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL
    )
    ''')
    
    # Create announcements table
    db.execute('''
    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create photo_requests table
    db.execute('''
    CREATE TABLE IF NOT EXISTS photo_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_name TEXT NOT NULL,
        description TEXT,
        filename TEXT NOT NULL,
        pending_path TEXT,
        approved_path TEXT,
        status TEXT DEFAULT 'pending' NOT NULL,
        submission_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        approval_date TIMESTAMP
    )
    ''')
    
    db.commit()

# --- Helper Functions ---
def is_logged_in():
    return session.get('logged_in', False)

def get_motd():
    """Read the Message of the Day from the file if it exists."""
    if os.path.exists(MOTD_PATH):
        try:
            with open(MOTD_PATH, 'r') as f:
                return f.read().strip()
        except Exception as e:
            print(f"Error reading MOTD file: {e}", flush=True)
    return None

def save_motd(message):
    """Save the Message of the Day to a file."""
    try:
        # Create data directory if it doesn't exist
        os.makedirs(os.path.dirname(MOTD_PATH), exist_ok=True)
        
        with open(MOTD_PATH, 'w') as f:
            f.write(message)
        return True
    except Exception as e:
        print(f"Error saving MOTD file: {e}", flush=True)
        return False

def delete_motd():
    """Delete the Message of the Day file if it exists."""
    if os.path.exists(MOTD_PATH):
        try:
            os.remove(MOTD_PATH)
            return True
        except Exception as e:
            print(f"Error deleting MOTD file: {e}", flush=True)
    return False

def login_required(f):
    def decorated_function(*args, **kwargs):
        if not is_logged_in():
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def get_user_by_username(username):
    return query_db('SELECT * FROM users WHERE username = ?', [username], one=True)

def check_password(stored_password_hash, password):
    return check_password_hash(stored_password_hash, password)

def create_user(username, password):
    password_hash = generate_password_hash(password)
    insert_db('INSERT INTO users (username, password_hash) VALUES (?, ?)', [username, password_hash])

def get_pending_requests():
    return query_db('SELECT * FROM photo_requests WHERE status = "pending" ORDER BY submission_date DESC')

def get_approved_requests():
    return query_db('SELECT * FROM photo_requests WHERE status = "approved" ORDER BY approval_date DESC')

def get_rejected_requests():
    return query_db('SELECT * FROM photo_requests WHERE status = "rejected" ORDER BY approval_date DESC')

def get_photo_request(id):
    return query_db('SELECT * FROM photo_requests WHERE id = ?', [id], one=True)

def create_photo_request(user_name, description, filename, pending_path):
    return insert_db(
        'INSERT INTO photo_requests (user_name, description, filename, pending_path, status) VALUES (?, ?, ?, ?, ?)',
        [user_name, description, filename, pending_path, 'pending']
    )

def update_photo_request_approved(id, approved_path, filename):
    update_db(
        'UPDATE photo_requests SET status = ?, approved_path = ?, filename = ?, approval_date = CURRENT_TIMESTAMP WHERE id = ?',
        ['approved', approved_path, filename, id]
    )

def update_photo_request_rejected(id):
    update_db(
        'UPDATE photo_requests SET status = ?, pending_path = NULL, approval_date = CURRENT_TIMESTAMP WHERE id = ?',
        ['rejected', id]
    )

# Initialize the database with app context
def init_app():
    # Create tables if they don't exist
    create_tables()
    
    # Get admin credentials from environment variables or use defaults
    admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'adminpass')
    
    # Create a default admin user if none exists
    if not get_user_by_username(admin_username):
        create_user(admin_username, admin_password)
        print(f"\nDefault admin user '{admin_username}' created with the provided password.\n!!! CHANGE THIS PASSWORD IMMEDIATELY IN PRODUCTION !!!\n", flush=True)
    
    # Add a default announcement if none exists
    if not query_db('SELECT * FROM announcements LIMIT 1'):
        insert_db(
            'INSERT INTO announcements (text) VALUES (?)',
            ["Welcome to the Admin Dashboard! Please update this announcement through the 'Announcements' section."]
        )
        print("Default announcement added.", flush=True)

# Call init_app with app context for each request
@app.before_request
def before_request():
    if not hasattr(g, 'initialized'):
        with app.app_context():
            init_app()
        g.initialized = True

# --- Main App Routes ---

# Serve the main HTML page
@app.route('/')
def index():
    # Get the Message of the Day if it exists
    motd = get_motd()
    return render_template('index.html', motd=motd)

# Serve images
@app.route('/images/<filename>')
def serve_image(filename):
    try:
        return send_from_directory(IMAGES_FOLDER_INTERNAL, filename)
    except FileNotFoundError:
        return jsonify({"error": "Image not found."}), 404

# Endpoint to get just a random image URL (fast response)
@app.route('/random-image')
def get_random_image():
    try:
        # Check if the directory exists
        if not os.path.exists(IMAGES_FOLDER_INTERNAL):
            print(f"Images folder not found at expected path: {IMAGES_FOLDER_INTERNAL}", flush=True)
            return jsonify({"error": f"Images folder not found on the server."}), 500

        # Get a list of all files and directories in the images folder
        files = os.listdir(IMAGES_FOLDER_INTERNAL)

        # Filter to include only common image extensions and exclude directories
        image_files = [f for f in files if os.path.isfile(os.path.join(IMAGES_FOLDER_INTERNAL, f)) and f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))]

        if not image_files:
            print(f"No image files found in {IMAGES_FOLDER_INTERNAL}", flush=True)
            return jsonify({"error": "No images found in the folder."}), 404

        # Select a random image file
        random_image_file = random.choice(image_files)
        
        # Add a random cachebuster to the URL to prevent browser caching of the image itself.
        cachebuster = random.randint(100000, 999999)
        image_url = f'/images/{random_image_file}?cb={cachebuster}'
        
        # Return just the image URL and filename for quick response
        return jsonify({
            "imageUrl": image_url,
            "filename": random_image_file
        })

    except Exception as e:
        print(f"An unexpected error occurred in get_random_image: {e}", flush=True)
        return jsonify({"error": f"An internal server error occurred: {e}"}), 500

# Endpoint to get source information for a specific image
@app.route('/image-source/<filename>')
def get_image_source(filename):
    # Initialize response outside the try block so it's accessible in except blocks
    response = None
    try:
        image_full_path = os.path.join(IMAGES_FOLDER_INTERNAL, filename)
        
        # Check if the image exists
        if not os.path.exists(image_full_path):
            return jsonify({"error": "Image not found."}), 404
            
        # --- Perform SauceNao Lookup ---
        saucenao_results = []
        try:
            with open(image_full_path, 'rb') as img_file:
                # Prepare data for the SauceNao API request
                files_payload = {'file': img_file}
                data_payload = {
                    'api_key': SAUCENAO_API_KEY,
                    'output_type': 2, # 2 for JSON output
                    'db': [5, 34] # Add this to search all databases
                }

                # Make the POST request to the SauceNao API
                response = requests.post(SAUCENAO_API_URL, data=data_payload, files=files_payload)
                print(f"SauceNao API response status code: {response.status_code}", flush=True)
                response.raise_for_status()
                print("SauceNao API request successful (HTTP 2xx).", flush=True)

                # Attempt to decode JSON
                saucenao_response_data = response.json()
                print("SauceNao API response JSON (if successful):", saucenao_response_data, flush=True)

                # Process the results
                if saucenao_response_data and 'results' in saucenao_response_data:
                    # Filter for results with a reasonable similarity score
                    min_similarity = 70 # You can adjust this threshold (0 to 100)
                    filtered_results = [
                        r for r in saucenao_response_data['results']
                        if r.get('header', {}).get('similarity') is not None and float(r['header']['similarity']) >= min_similarity
                    ]

                    # Sort results by similarity descending
                    sorted_results = sorted(filtered_results, key=lambda x: float(x.get('header', {}).get('similarity', 0)), reverse=True)

                    for result in sorted_results:
                        header = result.get('header', {})
                        data = result.get('data', {})

                        similarity = header.get('similarity')
                        # Try to find a source URL from external URLs, handle if list is empty
                        source_url = 'N/A'
                        if data.get('ext_urls'):
                            # Prioritize certain sources if needed, or just take the first one
                            source_url = data['ext_urls'][0] # Take the first URL in the list

                        # Try to find artist/creator information from various possible keys
                        artist = data.get('creator') or data.get('artist') or data.get('author_name') or 'N/A'
                        title = data.get('title') or data.get('source') or 'N/A' # Title might be in different keys
                        thumbnail = header.get('thumbnail') # Thumbnail URL

                        saucenao_results.append({
                            'similarity': similarity,
                            'source_url': source_url,
                            'artist': artist,
                            'title': title,
                            'thumbnail': thumbnail
                        })
                elif saucenao_response_data and 'results' not in saucenao_response_data:
                    print(f"SauceNao JSON response missing 'results' key (response data): {saucenao_response_data}", flush=True)
                else:
                    print("SauceNao API response JSON is empty or invalid (after successful request and JSON decode).", flush=True)

        except requests.exceptions.RequestException as e:
            print(f"Requests error during SauceNao API request for {filename}: {e}", flush=True)
            if e.response is not None:
                print(f"SauceNao error response status code (if available): {e.response.status_code}", flush=True)
                print(f"SauceNao error response text (if available): {e.response.text}", flush=True)
        except json.JSONDecodeError:
            print(f"Error decoding JSON from SauceNao API response for {filename}.", flush=True)
            if 'response' in locals() and response is not None:
                print(f"Raw SauceNao response text that caused JSONDecodeError: {response.text}", flush=True)
        except Exception as e:
            print(f"An unexpected error occurred during SauceNao lookup for {filename}: {e}", flush=True)

        # Return the source information
        return jsonify({"source_results": saucenao_results})

    except Exception as e:
        print(f"An unexpected error occurred in get_image_source: {e}", flush=True)
        return jsonify({"error": f"An internal server error occurred: {e}"}), 500

# Keep the original endpoint for backward compatibility
@app.route('/random-image-with-source')
def get_random_image_and_source():
    try:
        # Get a random image first
        image_response = get_random_image()
        
        # If there was an error getting the random image, return that error
        if image_response.status_code != 200:
            return image_response
            
        # Extract the image data from the response
        image_data = json.loads(image_response.get_data(as_text=True))
        
        if 'error' in image_data:
            return jsonify(image_data), 500
            
        # Get the filename from the image URL
        filename = image_data.get('filename')
        
        # Get the source information for this image
        source_response = get_image_source(filename)
        
        # If there was an error getting the source information, still return the image
        # but with empty source results
        if source_response.status_code != 200:
            return jsonify({
                "imageUrl": image_data.get('imageUrl'),
                "source_results": []
            })
            
        # Extract the source data from the response
        source_data = json.loads(source_response.get_data(as_text=True))
        
        # Combine the image URL and source results
        return jsonify({
            "imageUrl": image_data.get('imageUrl'),
            "source_results": source_data.get('source_results', [])
        })
        
    except Exception as e:
        print(f"An unexpected error occurred in get_random_image_and_source: {e}", flush=True)
        return jsonify({"error": f"An internal server error occurred: {e}"}), 500

# --- Admin Routes ---

# Login Page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if is_logged_in():
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = get_user_by_username(username)
        
        if user and check_password(user['password_hash'], password):
            session['logged_in'] = True
            session['username'] = username
            flash('Logged in successfully.', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('admin_templates/login.html')

# Logout Route
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# Admin Dashboard
@app.route('/admin')
@login_required
def admin_dashboard():
    # Get pending photo requests
    pending_requests = get_pending_requests()
    # Get approved photo requests
    approved_requests = get_approved_requests()
    # Get rejected photo requests
    rejected_requests = get_rejected_requests()
    # Get current MOTD
    current_motd = get_motd() or ""
    
    return render_template('admin_templates/admin_dashboard.html', 
                          pending_requests=pending_requests, 
                          approved_requests=approved_requests, 
                          rejected_requests=rejected_requests,
                          current_motd=current_motd)

# Update MOTD
@app.route('/update_motd', methods=['POST'])
@login_required
def update_motd():
    motd_text = request.form.get('motd_text', '').strip()
    
    if motd_text:
        # Save the MOTD to the file
        if save_motd(motd_text):
            flash('Message of the Day updated successfully!', 'success')
        else:
            flash('Error updating Message of the Day.', 'danger')
    else:
        # If the MOTD is empty, delete the file
        if delete_motd():
            flash('Message of the Day removed.', 'info')
        else:
            flash('Error removing Message of the Day.', 'danger')
    
    return redirect(url_for('admin_dashboard'))

# Delete MOTD
@app.route('/delete_motd')
@login_required
def delete_motd_route():
    if delete_motd():
        flash('Message of the Day removed.', 'success')
    else:
        flash('Error removing Message of the Day.', 'danger')
    
    return redirect(url_for('admin_dashboard'))

# Approve Photo
@app.route('/approve/<int:id>')
@login_required
def approve_photo(id):
    photo_request = get_photo_request(id)
    if photo_request and photo_request['status'] == 'pending' and photo_request['pending_path'] and os.path.exists(photo_request['pending_path']):
        approved_filename = photo_request['filename']
        destination_path = os.path.join(IMAGES_FOLDER_INTERNAL, approved_filename)

        # Handle potential filename collisions
        counter = 1
        original_filename_no_ext, file_extension = os.path.splitext(approved_filename)
        while os.path.exists(destination_path):
            approved_filename = f"{original_filename_no_ext}_{counter}{file_extension}"
            destination_path = os.path.join(IMAGES_FOLDER_INTERNAL, approved_filename)
            counter += 1

        try:
            shutil.move(photo_request['pending_path'], destination_path)
            update_photo_request_approved(id, destination_path, approved_filename)
            flash(f'Photo request {id} approved and moved to images folder as {approved_filename}!', 'success')
        except Exception as e:
            flash(f'Error approving photo request {id}: {e}', 'danger')
    else:
        flash(f'Photo request {id} cannot be approved (already approved/rejected or pending file missing).', 'warning')

    return redirect(url_for('admin_dashboard'))

# Reject Photo
@app.route('/reject/<int:id>')
@login_required
def reject_photo(id):
    photo_request = get_photo_request(id)
    if photo_request and photo_request['status'] == 'pending':
        if photo_request['pending_path'] and os.path.exists(photo_request['pending_path']):
            try:
                os.remove(photo_request['pending_path'])
                flash(f'Pending file for request {id} deleted.', 'info')
            except Exception as e:
                flash(f'Error deleting pending file for request {id}: {e}', 'danger')

        update_photo_request_rejected(id)
        flash(f'Photo request {id} rejected.', 'success')
    else:
        flash(f'Photo request {id} cannot be rejected (already approved/rejected).', 'warning')

    return redirect(url_for('admin_dashboard'))

# Serve Pending Image
@app.route('/pending_uploads/<path:filename>')
@login_required
def serve_pending_image(filename):
    try:
        return send_from_directory(PENDING_UPLOADS_FOLDER, filename)
    except FileNotFoundError:
        return "Pending image not found for preview.", 404

# Serve Approved Image
@app.route('/approved_images/<path:filename>')
@login_required
def serve_approved_image(filename):
    try:
        return send_from_directory(IMAGES_FOLDER_INTERNAL, filename)
    except FileNotFoundError:
        return "Approved image not found for preview.", 404

# Photo Submission Form
@app.route('/submit_photo', methods=['GET', 'POST'])
def submit_photo():
    if request.method == 'POST':
        user_name = request.form.get('user_name', 'Anonymous')
        description = request.form.get('description', '').strip()

        if 'photo_file' not in request.files:
            flash('No file part in the request.', 'danger')
            return redirect(url_for('submit_photo'))

        file = request.files['photo_file']

        if file.filename == '':
            flash('No file selected.', 'warning')
            return redirect(url_for('submit_photo'))

        ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
        def allowed_file(filename):
            return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

        if file and allowed_file(file.filename):
            filename_secured = secure_filename(file.filename)
            file_path = os.path.join(PENDING_UPLOADS_FOLDER, filename_secured)

            # Handle potential filename collisions in pending_uploads
            counter = 1
            original_filename_no_ext, file_extension = os.path.splitext(filename_secured)
            while os.path.exists(file_path):
                filename_secured = f"{original_filename_no_ext}_{counter}{file_extension}"
                file_path = os.path.join(PENDING_UPLOADS_FOLDER, filename_secured)
                counter += 1

            try:
                file.save(file_path)
                create_photo_request(user_name, description, filename_secured, file_path)
                flash('Your photo request has been submitted successfully! We will review it soon.', 'success')
                return redirect(url_for('submit_photo'))
            except Exception as e:
                print(f"Error saving file: {e}")
                flash('An error occurred during file upload. Please try again.', 'danger')
        else:
            flash('File type not allowed. Please upload an image (png, jpg, jpeg, gif).', 'danger')

    return render_template('admin_templates/submit_photo.html')

# Admin Home Page
@app.route('/admin_home')
def admin_home():
    return render_template('admin_templates/admin_home.html')

if __name__ == '__main__':
    # Ensure the data directories exist
    os.makedirs(IMAGES_FOLDER_INTERNAL, exist_ok=True)
    os.makedirs(PENDING_UPLOADS_FOLDER, exist_ok=True)
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    
    # Initialize the database
    with app.app_context():
        create_tables()
        
        # Get admin credentials from environment variables or use defaults
        admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
        admin_password = os.environ.get('ADMIN_PASSWORD', 'adminpass')
        
        # Create a default admin user if none exists
        if not get_user_by_username(admin_username):
            create_user(admin_username, admin_password)
            print(f"\nDefault admin user '{admin_username}' created with the provided password.\n!!! CHANGE THIS PASSWORD IMMEDIATELY IN PRODUCTION !!!\n", flush=True)
        
        # Add a default announcement if none exists
        if not query_db('SELECT * FROM announcements LIMIT 1'):
            insert_db(
                'INSERT INTO announcements (text) VALUES (?)',
                ["Welcome to the Admin Dashboard! Please update this announcement through the 'Announcements' section."]
            )
            print("Default announcement added.", flush=True)
    
    print("Running Flask development server...", flush=True)
    app.run(host='0.0.0.0', port=5000, debug=False)

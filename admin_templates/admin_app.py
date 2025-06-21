import os
import shutil # For moving files
import sqlite3
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- Flask App Configuration ---
admin_app = Flask(__name__, template_folder='.')

# IMPORTANT: Change this to a strong, random key in production!
admin_app.config['SECRET_KEY'] = 'another_super_secret_key_for_admin_app'

# Database configuration
DATABASE = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'site.db')

# --- File Upload Configuration ---
# Define the folders for pending and approved images
admin_app.config['UPLOAD_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'pending_uploads')
# This points to the 'images' folder in your main project root
admin_app.config['APPROVED_IMAGES_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'images')
admin_app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16 Megabytes limit for file uploads

# Ensure these directories exist when the app starts
os.makedirs(admin_app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(admin_app.config['APPROVED_IMAGES_FOLDER'], exist_ok=True)

# --- Database Helper Functions ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

# Initialize the database before the first request
@admin_app.before_first_request
def init_app():
    # Create tables if they don't exist
    create_tables()
    
    # Create a default admin user if none exists
    if not get_user_by_username('admin'):
        create_user('admin', 'adminpass')
        print("\nDefault admin user 'admin' created with password 'adminpass'.\n!!! CHANGE THIS PASSWORD IMMEDIATELY IN PRODUCTION !!!\n", flush=True)
    
    # Add a default announcement if none exists
    if not query_db('SELECT * FROM announcements LIMIT 1'):
        insert_db(
            'INSERT INTO announcements (text) VALUES (?)',
            ["Welcome to the Admin Dashboard! Please update this announcement through the 'Announcements' section."]
        )
        print("Default announcement added for admin app.", flush=True)

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

@admin_app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with admin_app.app_context():
        db = get_db()
        with admin_app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()

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

# --- Flask Routes ---

# Login Page
@admin_app.route('/login', methods=['GET', 'POST'])
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
    
    return render_template('login.html')

# Logout Route
@admin_app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# Admin Dashboard
@admin_app.route('/admin')
@login_required
def admin_dashboard():
    # Get pending photo requests
    pending_requests = get_pending_requests()
    # Get approved photo requests
    approved_requests = get_approved_requests()
    # Get rejected photo requests
    rejected_requests = get_rejected_requests()
    
    return render_template('admin_dashboard.html', 
                          pending_requests=pending_requests, 
                          approved_requests=approved_requests, 
                          rejected_requests=rejected_requests)

# Approve Photo
@admin_app.route('/approve/<int:id>')
@login_required
def approve_photo(id):
    photo_request = get_photo_request(id)
    if photo_request and photo_request['status'] == 'pending' and photo_request['pending_path'] and os.path.exists(photo_request['pending_path']):
        approved_filename = photo_request['filename']
        destination_path = os.path.join(admin_app.config['APPROVED_IMAGES_FOLDER'], approved_filename)

        # Handle potential filename collisions
        counter = 1
        original_filename_no_ext, file_extension = os.path.splitext(approved_filename)
        while os.path.exists(destination_path):
            approved_filename = f"{original_filename_no_ext}_{counter}{file_extension}"
            destination_path = os.path.join(admin_app.config['APPROVED_IMAGES_FOLDER'], approved_filename)
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
@admin_app.route('/reject/<int:id>')
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
@admin_app.route('/pending_uploads/<path:filename>')
@login_required
def serve_pending_image(filename):
    try:
        return send_from_directory(admin_app.config['UPLOAD_FOLDER'], filename)
    except FileNotFoundError:
        return "Pending image not found for preview.", 404

# Serve Approved Image
@admin_app.route('/images/<path:filename>')
def serve_approved_image(filename):
    try:
        return send_from_directory(admin_app.config['APPROVED_IMAGES_FOLDER'], filename)
    except FileNotFoundError:
        return "Approved image not found for preview.", 404

# Photo Submission Form
@admin_app.route('/submit_photo', methods=['GET', 'POST'])
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
            file_path = os.path.join(admin_app.config['UPLOAD_FOLDER'], filename_secured)

            # Handle potential filename collisions in pending_uploads
            counter = 1
            original_filename_no_ext, file_extension = os.path.splitext(filename_secured)
            while os.path.exists(file_path):
                filename_secured = f"{original_filename_no_ext}_{counter}{file_extension}"
                file_path = os.path.join(admin_app.config['UPLOAD_FOLDER'], filename_secured)
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

    return render_template('submit_photo.html')

# Home Page
@admin_app.route('/')
def admin_home():
    return render_template('admin_home.html')

# --- Main Run Block ---
if __name__ == '__main__':
    with admin_app.app_context():
        # Create tables if they don't exist
        create_tables()

        # Create a default admin user if none exists
        if not get_user_by_username('admin'):
            create_user('admin', 'adminpass')
            print("\nDefault admin user 'admin' created with password 'adminpass'.\n!!! CHANGE THIS PASSWORD IMMEDIATELY IN PRODUCTION !!!\n", flush=True)

        # Add a default announcement if none exists
        if not query_db('SELECT * FROM announcements LIMIT 1'):
            insert_db(
                'INSERT INTO announcements (text) VALUES (?)',
                ["Welcome to the Admin Dashboard! Please update this announcement through the 'Announcements' section."]
            )
            print("Default announcement added for admin app.", flush=True)

    print("Running Admin Flask development server on port 5001...", flush=True)
    admin_app.run(debug=True, port=5001)

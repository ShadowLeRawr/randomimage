import os
import shutil # For moving files
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- Flask App Configuration ---
admin_app = Flask(__name__, template_folder='.')

# IMPORTANT: Change this to a strong, random key in production!
admin_app.config['SECRET_KEY'] = 'another_super_secret_key_for_admin_app'

# Database configuration (using SQLite for simplicity)
admin_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
admin_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- File Upload Configuration ---
# Define the folders for pending and approved images
admin_app.config['UPLOAD_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'pending_uploads')
# This points to the 'images' folder in your main project root
admin_app.config['APPROVED_IMAGES_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', 'images')
admin_app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16 Megabytes limit for file uploads

# Ensure these directories exist when the app starts
os.makedirs(admin_app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(admin_app.config['APPROVED_IMAGES_FOLDER'], exist_ok=True)

# --- Database Initialization ---
db = SQLAlchemy(admin_app)

# --- Define Database Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    last_updated = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    def __repr__(self):
        return f"Announcement('{self.text[:30]}...')"

class PhotoRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    filename = db.Column(db.String(255), nullable=False) # Original filename from user
    pending_path = db.Column(db.String(500), nullable=True) # Full path in pending_uploads
    approved_path = db.Column(db.String(500), nullable=True) # Full path in images folder
    # Status: 'pending', 'approved', 'rejected'
    status = db.Column(db.String(20), default='pending', nullable=False)
    submission_date = db.Column(db.DateTime, default=db.func.now())
    approval_date = db.Column(db.DateTime, nullable=True) # When it was approved/rejected

    def __repr__(self):
        return f"PhotoRequest('{self.user_name}', '{self.filename}', '{self.status}')"

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

# --- Flask Routes ---

# Login Page
@admin_app.route('/login', methods=['GET', 'POST'])
def login():
    if is_logged_in():
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
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
    pending_requests = PhotoRequest.query.filter_by(status='pending').order_by(PhotoRequest.submission_date.desc()).all()
    # Get approved photo requests
    approved_requests = PhotoRequest.query.filter_by(status='approved').order_by(PhotoRequest.approval_date.desc()).all()
    # Get rejected photo requests
    rejected_requests = PhotoRequest.query.filter_by(status='rejected').order_by(PhotoRequest.approval_date.desc()).all()
    
    return render_template('admin_dashboard.html', 
                          pending_requests=pending_requests, 
                          approved_requests=approved_requests, 
                          rejected_requests=rejected_requests)

# Approve Photo
@admin_app.route('/approve/<int:id>')
@login_required
def approve_photo(id):
    photo_request = PhotoRequest.query.get_or_404(id)
    if photo_request.status == 'pending' and photo_request.pending_path and os.path.exists(photo_request.pending_path):
        approved_filename = photo_request.filename
        destination_path = os.path.join(admin_app.config['APPROVED_IMAGES_FOLDER'], approved_filename)

        # Handle potential filename collisions
        counter = 1
        original_filename_no_ext, file_extension = os.path.splitext(approved_filename)
        while os.path.exists(destination_path):
            approved_filename = f"{original_filename_no_ext}_{counter}{file_extension}"
            destination_path = os.path.join(admin_app.config['APPROVED_IMAGES_FOLDER'], approved_filename)
            counter += 1

        try:
            shutil.move(photo_request.pending_path, destination_path)
            photo_request.status = 'approved'
            photo_request.approved_path = destination_path
            photo_request.filename = approved_filename
            photo_request.approval_date = datetime.now()
            db.session.commit()
            flash(f'Photo request {id} approved and moved to images folder as {approved_filename}!', 'success')
        except Exception as e:
            flash(f'Error approving photo request {id}: {e}', 'danger')
            db.session.rollback()
    else:
        flash(f'Photo request {id} cannot be approved (already approved/rejected or pending file missing).', 'warning')

    return redirect(url_for('admin_dashboard'))

# Reject Photo
@admin_app.route('/reject/<int:id>')
@login_required
def reject_photo(id):
    photo_request = PhotoRequest.query.get_or_404(id)
    if photo_request.status == 'pending':
        if photo_request.pending_path and os.path.exists(photo_request.pending_path):
            try:
                os.remove(photo_request.pending_path)
                flash(f'Pending file for request {id} deleted.', 'info')
            except Exception as e:
                flash(f'Error deleting pending file for request {id}: {e}', 'danger')

        photo_request.status = 'rejected'
        photo_request.approval_date = datetime.now()
        photo_request.pending_path = None
        db.session.commit()
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
                new_request = PhotoRequest(
                    user_name=user_name,
                    description=description,
                    filename=filename_secured,
                    pending_path=file_path,
                    status='pending'
                )
                db.session.add(new_request)
                db.session.commit()
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
        db.create_all()

        # Create a default admin user if none exists
        if not User.query.filter_by(username='admin').first():
            admin_user = User(username='admin')
            admin_user.set_password('adminpass')
            db.session.add(admin_user)
            db.session.commit()
            print("\nDefault admin user 'admin' created with password 'adminpass'.\n!!! CHANGE THIS PASSWORD IMMEDIATELY IN PRODUCTION !!!\n", flush=True)

        # Add a default announcement if none exists
        if not Announcement.query.first():
            default_announcement = Announcement(
                text="Welcome to the Admin Dashboard! Please update this announcement through the 'Announcements' section."
            )
            db.session.add(default_announcement)
            db.session.commit()
            print("Default announcement added for admin app.", flush=True)

    print("Running Admin Flask development server on port 5001...", flush=True)
    admin_app.run(debug=True, port=5001)

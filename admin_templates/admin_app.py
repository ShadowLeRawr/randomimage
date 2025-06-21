import os
import shutil # For moving files
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin, BaseView, expose
from flask_admin.contrib.sqla import ModelView
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- Flask App Configuration ---
# IMPORTANT: template_folder='admin_templates' tells this Flask app to look for templates here
admin_app = Flask(__name__, template_folder='admin_templates')

# IMPORTANT: Change this to a strong, random key in production!
# You can generate one using: os.urandom(24).hex()
admin_app.config['SECRET_KEY'] = 'another_super_secret_key_for_admin_app' # MUST BE DIFFERENT FROM YOUR MAIN APP

# Database configuration (using SQLite for simplicity)
admin_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db' # This DB will be created in your project root
admin_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Suppress a warning

# --- File Upload Configuration ---
# Define the folders for pending and approved images
# os.path.abspath(os.path.dirname(__file__)) gets the directory of the current script (admin_app.py)
admin_app.config['UPLOAD_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'pending_uploads')
# This points to the 'images' folder in your main project root, where approved images will go
admin_app.config['APPROVED_IMAGES_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'images')
admin_app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16 Megabytes limit for file uploads

# Ensure these directories exist when the app starts
os.makedirs(admin_app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(admin_app.config['APPROVED_IMAGES_FOLDER'], exist_ok=True) # Ensure 'images' also exists, though your main app might create it

# --- Database Initialization ---
db = SQLAlchemy(admin_app)

# --- Flask-Login Setup ---
login_manager = LoginManager()
login_manager.init_app(admin_app)
login_manager.login_view = 'login' # Define the login route

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Define Database Models ---
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

# --- Flask-Admin Custom Views ---
class AuthenticatedModelView(ModelView):
    # Ensures only logged-in users can access this view
    def is_accessible(self):
        return current_user.is_authenticated

    def inaccessible_callback(self, name, **kwargs):
        # Redirect to login page if user is not authenticated
        return redirect(url_for('login', next=request.url))

class PhotoRequestAdminView(AuthenticatedModelView):
    # Custom formatter for displaying image previews in the list
    def _list_thumbnail_formatter(view, context, model, name):
        if model.filename and (model.status == 'pending' or model.status == 'approved'):
            if model.status == 'pending' and model.pending_path:
                # Link to the route that serves pending images from admin_app
                return f'<img src="{url_for("serve_pending_image", filename=os.path.basename(model.pending_path))}" style="max-width:100px; max-height:100px; object-fit: cover;">'
            elif model.status == 'approved' and model.approved_path:
                # Link to the main app's image serving route (assuming Nginx handles this in production)
                # For development, 'main_app_serve_image' is a placeholder route in this admin_app
                return f'<img src="{url_for("main_app_serve_image", filename=os.path.basename(model.approved_path))}" style="max-width:100px; max-height:100px; object-fit: cover;">'
        return ''

    # Define how columns appear in the list view
    column_list = ('id', 'user_name', 'description', 'filename', 'Image Preview', 'status', 'submission_date', 'approval_date')
    column_default_sort = ('submission_date', True) # Sort by newest first
    column_labels = dict(user_name='User', description='Description') # Nicer labels
    column_formatters = {
        'Image Preview': _list_thumbnail_formatter # Apply the formatter to the 'Image Preview' column
    }

    # Exclude certain fields from the create/edit form in the admin (they are managed automatically)
    form_excluded_columns = ['filename', 'pending_path', 'approved_path', 'submission_date', 'approval_date']
    can_create = False # Photo requests are created by users via the public form
    can_delete = True  # Admin can delete requests

    # Custom actions (Approve/Reject buttons)
    @expose('/approve/<int:id>', methods=('GET',))
    @login_required
    def approve_photo(self, id):
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
                photo_request.approved_path = destination_path # Store full path to approved image
                photo_request.filename = approved_filename # Update filename if it was changed due to collision
                photo_request.approval_date = datetime.now()
                db.session.commit()
                flash(f'Photo request {id} approved and moved to images folder as {approved_filename}!', 'success')
            except Exception as e:
                flash(f'Error approving photo request {id}: {e}', 'danger')
                db.session.rollback()
        else:
            flash(f'Photo request {id} cannot be approved (already approved/rejected or pending file missing).', 'warning')

        return redirect(url_for('photorequest.index_view'))

    @expose('/reject/<int:id>', methods=('GET',))
    @login_required
    def reject_photo(self, id):
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
            photo_request.pending_path = None # Clear pending path as file is gone
            db.session.commit()
            flash(f'Photo request {id} rejected.', 'success')
        else:
            flash(f'Photo request {id} cannot be rejected (already approved/rejected).', 'warning')

        return redirect(url_for('photorequest.index_view'))

    # Add custom action buttons to each row in the list view
    column_extra_actions = [
        # Button for approving pending requests
        {'title': 'Approve', 'url': 'photorequest.approve_photo', 'icon': 'fa-check', 'class': 'btn btn-sm btn-success', 'condition': lambda model: model.status == 'pending'},
        # Button for rejecting pending requests
        {'title': 'Reject', 'url': 'photorequest.reject_photo', 'icon': 'fa-times', 'class': 'btn btn-sm btn-danger', 'condition': lambda model: model.status == 'pending'},
    ]

# Initialize Flask-Admin with the admin_app
admin = Admin(admin_app, name='Admin Dashboard', template_mode='bootstrap3', url='/admin') # Dashboard will be at /admin

# Add views to the admin dashboard
admin.add_view(AuthenticatedModelView(Announcement, db.session, category='Content', name='Announcements'))
admin.add_view(PhotoRequestAdminView(PhotoRequest, db.session, category='Content', name='Photo Requests'))
admin.add_view(AuthenticatedModelView(User, db.session, category='Administration', name='Users'))

# --- Flask Routes for admin_app ---

# Route to serve approved images for preview within the admin dashboard
# This acts as a proxy for your main app's /images route for the admin's view
@admin_app.route('/images/<path:filename>') # Use path converter for filenames with slashes (though unlikely for images)
def main_app_serve_image(filename):
    try:
        # Serves from the same 'images' directory that your main app uses
        return send_from_directory(admin_app.config['APPROVED_IMAGES_FOLDER'], filename)
    except FileNotFoundError:
        return "Approved image not found for preview.", 404

# Route to serve pending images for preview within the admin dashboard
@admin_app.route('/pending_uploads/<path:filename>')
def serve_pending_image(filename):
    try:
        return send_from_directory(admin_app.config['UPLOAD_FOLDER'], filename)
    except FileNotFoundError:
        return "Pending image not found for preview.", 404

# Login Page
@admin_app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # If already logged in, redirect to the admin dashboard index
        return redirect(url_for('admin.index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Logged in successfully.', 'success')
            next_page = request.args.get('next') # Redirect to the page user was trying to access
            return redirect(next_page or url_for('admin.index'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('login.html')

# Logout Route
@admin_app.route('/logout')
@login_required # Requires login to access
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login')) # Redirect to login page after logout

# Default route for the admin_app (simple home page)
@admin_app.route('/')
def admin_home():
    return render_template('admin_home.html')

# Photo Submission Route (publicly accessible)
@admin_app.route('/submit_photo', methods=['GET', 'POST'])
def submit_photo():
    if request.method == 'POST':
        user_name = request.form.get('user_name', 'Anonymous')
        description = request.form.get('description', '').strip()

        # Check if a file was sent as part of the request
        if 'photo_file' not in request.files:
            flash('No file part in the request.', 'danger')
            return redirect(url_for('submit_photo'))

        file = request.files['photo_file']

        # If the user selected the file input but didn't choose a file
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
                file.save(file_path) # Save the uploaded file
                new_request = PhotoRequest(
                    user_name=user_name,
                    description=description,
                    filename=filename_secured, # Store the actual filename used on disk
                    pending_path=file_path, # Store the full path in pending folder
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

# Context processor to make datetime.utcnow available in templates for date formatting
@admin_app.context_processor
def inject_now():
    return {'now': datetime.utcnow}


# --- Main Run Block for admin_app ---
if __name__ == '__main__':
    with admin_app.app_context():
        db.create_all() # Create all tables defined in models if they don't exist

        # Create a default admin user if none exists
        if not User.query.filter_by(username='admin').first():
            admin_user = User(username='admin')
            admin_user.set_password('adminpass') # !!! CHANGE THIS PASSWORD IMMEDIATELY IN PRODUCTION !!!
            db.session.add(admin_user)
            db.session.commit()
            print("\nDefault admin user 'admin' created with password 'adminpass'.\n!!! CHANGE THIS PASSWORD IMMEDIATELY IN PRODUCTION !!!\n", flush=True)

        # Add a default announcement if none exists (for the admin app's announcement section)
        if not Announcement.query.first():
            default_announcement = Announcement(
                text="Welcome to the Admin Dashboard! Please update this announcement through the 'Announcements' section."
            )
            db.session.add(default_announcement)
            db.session.commit()
            print("Default announcement added for admin app.", flush=True)

    print("Running Admin Flask development server on port 5001...", flush=True)
    admin_app.run(debug=True, port=5001) # Runs on a different port (5001) than your main app (5000)

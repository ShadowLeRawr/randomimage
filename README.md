# Random Image Application

A web application that displays random images with source information, featuring an admin panel for content management.

## Features

### Main Application
- Random image display with source information lookup via SauceNao API
- Clean, responsive UI with dark mode
- API endpoint for retrieving random images with source details

### Admin Panel
- Secure admin dashboard with authentication
- Content management for announcements
- Photo request submission and moderation system
- User management capabilities

## Project Structure

```
.
├── app.py                  # Main Flask application
├── admin_templates/        # Admin application files
│   └── admin_app.py        # Admin Flask application
├── images/                 # Approved images storage
├── my_random_images/       # Additional image storage
├── templates/              # HTML templates
│   ├── admin.html          # Admin interface template
│   └── index.html          # Main site template
├── nginx/                  # Nginx configuration
│   └── conf.d/             # Nginx site configurations
├── Dockerfile              # Docker image definition
├── docker-compose.yaml     # Docker Compose configuration
└── requirements.txt        # Python dependencies
```

## Prerequisites

- Docker and Docker Compose
- SauceNao API key (for image source lookup)

## Installation & Setup

1. Clone the repository:
   ```
   git clone git@github.com:ShadowLeRawr/randomimage.git
   cd randomimage
   ```

2. Configure environment variables:
   - Create a `.env` file in the project root with:
     ```
     SAUCENAO_API_KEY=your_api_key_here
     ```

3. Build and start the containers:
   ```
   docker-compose up -d
   ```

4. Access the application:
   - Main site: http://localhost
   - Admin panel: http://localhost/admin
   - Photo submission: http://localhost/submit_photo

## Docker Configuration

The application is containerized using Docker with three services:

1. **main-app**: The primary Flask application serving random images
2. **admin-app**: The admin panel for content management
3. **nginx**: Web server that handles routing and serves static files

## Development

### Local Development Setup

1. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Run the main application:
   ```
   python app.py
   ```

3. Run the admin application (in a separate terminal):
   ```
   cd admin_templates
   python admin_app.py
   ```

### Default Admin Credentials

- Username: `admin`
- Password: `adminpass`

**IMPORTANT**: Change the default password immediately in production!

## Production Deployment

For production deployment:

1. Update the Nginx configuration in `nginx/conf.d/default.conf`:
   - Set the appropriate `server_name`
   - Uncomment and configure the HTTPS server block
   - Add SSL certificates to `nginx/ssl/`

2. Modify the admin password:
   - Access the admin panel
   - Navigate to Users section
   - Update the admin user password

3. Set proper permissions for data directories:
   ```
   chmod -R 755 images
   chmod -R 755 admin_templates/pending_uploads
   ```

## Security Considerations

- The application uses SQLite by default. For production, consider using a more robust database like PostgreSQL.
- Always change default credentials before deployment.
- Regularly update dependencies to address security vulnerabilities.
- Configure proper file upload limits and validation.

## License

[Specify your license information here]

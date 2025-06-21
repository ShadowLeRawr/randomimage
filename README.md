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
├── app.py                  # Main Flask application with integrated admin functionality
├── data/                   # Data directory
│   ├── images/             # Approved images storage
│   ├── pending_images/     # Pending image uploads
│   └── sqlite/             # SQLite database storage
├── admin_templates/        # Admin templates
├── templates/              # HTML templates
│   ├── admin.html          # Admin interface template
│   └── index.html          # Main site template
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
     ADMIN_USERNAME=your_admin_username
     ADMIN_PASSWORD=your_admin_password
     ```
   - If ADMIN_USERNAME and ADMIN_PASSWORD are not provided, the default values 'admin' and 'adminpass' will be used.

3. Build and start the containers:
   ```
   docker-compose up -d
   ```

4. Access the application:
   - Main site: http://localhost:5000
   - Admin panel: http://localhost:5000/admin
   - Photo submission: http://localhost:5000/submit_photo

## Live Demo

A live demo of the application is hosted at:
- Main site: https://slitsndicks.furryrefuge.com
- Admin panel: https://slitsndicksadmin.furryrefuge.com

## Docker Configuration

The application is containerized using Docker with a single service that handles both the main application and admin functionality. The application is designed to run behind a reverse proxy.

## Development

### Local Development Setup

1. Install Python dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Run the application:
   ```
   python app.py
   ```

### Default Admin Credentials

- Username: `admin`
- Password: `adminpass`

**IMPORTANT**: Change the default password immediately in production!

## Production Deployment

For production deployment:

1. Configure your reverse proxy to forward requests to the application container.

2. Modify the admin password:
   - Access the admin panel
   - Navigate to Users section
   - Update the admin user password

3. Set proper permissions for data directories:
   ```
   chmod -R 755 data
   ```

## Security Considerations

- The application uses SQLite by default. For production, consider using a more robust database like PostgreSQL.
- Always change default credentials before deployment.
- Regularly update dependencies to address security vulnerabilities.
- Configure proper file upload limits and validation.

import os
import random
from flask import Flask, jsonify, render_template, send_from_directory
import requests
import json

app = Flask(__name__)

# Replace with your actual SauceNao API key
SAUCENAO_API_KEY = os.environ.get('SAUCENAO_API_KEY', 'APIKEYHERE')

# SauceNao API URL
SAUCENAO_API_URL = 'https://saucenao.com/search.php'

# The path to the images folder relative to the Flask app
IMAGES_FOLDER_INTERNAL = 'images'

# Serve the main HTML page
@app.route('/')
def index():
    # This renders the index.html file located in the same directory as app.py
    return render_template('index.html')

# This route is crucial for Nginx to serve the images directly
# Nginx is configured to serve files from /images/ based on the filesystem path
# We still define this route in Flask mainly for completeness and local testing
# with Flask's development server, although Nginx handles it in production.
@app.route('/images/<filename>')
def serve_image(filename):
     # In a production environment with Nginx, this Flask route is typically not hit for image requests.
     # Nginx serves the files directly based on its configuration.
     # We keep it here as a fallback or for development.
     try:
         # SECURITY NOTE: send_from_directory is generally safe as it prevents directory traversal,
         # but ensure IMAGES_FOLDER_INTERNAL is correct and images are within that directory.
         return send_from_directory(IMAGES_FOLDER_INTERNAL, filename)
     except FileNotFoundError:
         return jsonify({"error": "Image not found."}), 404


# Endpoint to get a random image and its SauceNao source information
@app.route('/random-image-with-source')
def get_random_image_and_source():
    # Initialize response outside the try block so it's accessible in except blocks
    response = None
    try:
        # Construct the absolute path to the images folder
        images_path = os.path.join(os.path.dirname(__file__), IMAGES_FOLDER_INTERNAL)

        # Check if the directory exists
        if not os.path.exists(images_path):
             # Log the error for debugging
             print(f"Images folder not found at expected path: {images_path}", flush=True)
             return jsonify({"error": f"Images folder not found on the server."}), 500

        # Get a list of all files and directories in the images folder
        files = os.listdir(images_path)

        # Filter to include only common image extensions and exclude directories
        image_files = [f for f in files if os.path.isfile(os.path.join(images_path, f)) and f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))]

        if not image_files:
            # Log if no images are found
            print(f"No image files found in {images_path}", flush=True)
            return jsonify({"error": "No images found in the folder."}), 404

        # Select a random image file
        random_image_file = random.choice(image_files)
        image_full_path = os.path.join(images_path, random_image_file)

        # Construct the URL path that Nginx will serve.
        # This path should match the Nginx configuration for serving images.
        # Add a random cachebuster to the URL to prevent browser/Nginx caching of the image itself.
        cachebuster = random.randint(100000, 999999) # Generate a random number
        image_url = f'/images/{random_image_file}?cb={cachebuster}' # Append as a query parameter

        # --- Perform SauceNao Lookup ---
        saucenao_results = []
        try:
            # Ensure the image file actually exists before trying to open it
            if os.path.exists(image_full_path):
                with open(image_full_path, 'rb') as img_file:
                    # Prepare data for the SauceNao API request
                    # Send the image file bytes directly
                    files_payload = {'file': img_file}
                    data_payload = {
                        'api_key': SAUCENAO_API_KEY,
                        'output_type': 2, # 2 for JSON output
                        'db': [5, 34] # Add this to search all databases
                    }

                    # Make the POST request to the SauceNao API
                    response = requests.post(SAUCENAO_API_URL, data=data_payload, files=files_payload)
                    # Log the status code before potentially raising an exception
                    print(f"SauceNao API response status code: {response.status_code}", flush=True)
                    response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
                    print("SauceNao API request successful (HTTP 2xx).", flush=True)


                    # Attempt to decode JSON - this is where the JSONDecodeError happens
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

                        # Limit the number of results returned (optional)
                        # sorted_results = sorted_results[:5] # Example: return only the top 5 results


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
                         # SauceNao returned JSON, but it doesn't have a 'results' key.
                         # This might indicate an API error reported in a different format within the JSON.
                         print(f"SauceNao JSON response missing 'results' key (response data): {saucenao_response_data}", flush=True)
                    else:
                        # This case might happen if the response.json() was successful but returned None or an empty structure
                        print("SauceNao API response JSON is empty or invalid (after successful request and JSON decode).", flush=True)


        except requests.exceptions.RequestException as e:
            # This block handles HTTP errors (like 403, 429) caught by raise_for_status()
            print(f"Requests error during SauceNao API request for {random_image_file}: {e}", flush=True)
            # Attempt to log the response text if the request failed after getting a response
            if e.response is not None:
                print(f"SauceNao error response status code (if available): {e.response.status_code}", flush=True)
                print(f"SauceNao error response text (if available): {e.response.text}", flush=True)
            # Continue without SauceNao results
        except json.JSONDecodeError:
            # *** THIS BLOCK HANDLES JSON DECODING ERRORS ***
            print(f"Error decoding JSON from SauceNao API response for {random_image_file}.", flush=True)
            # Log the raw response text received from SauceNao that caused the error
            if 'response' in locals() and response is not None:
                print(f"Raw SauceNao response text that caused JSONDecodeError: {response.text}", flush=True)
            # Continue without SauceNao results
        except FileNotFoundError:
             # Handles the case where the image file selected randomly somehow doesn't exist when trying to open it
             print(f"Image file not found locally for SauceNao lookup: {image_full_path}", flush=True)
             # Continue without SauceNao results
        except Exception as e:
            # Handles any other unexpected errors during the lookup process
            print(f"An unexpected error occurred during SauceNao lookup for {random_image_file}: {e}", flush=True)
             # Continue without SauceNao results


        # Return both the image URL (with cachebuster) and filtered SauceNao results
        # Even if SauceNao lookup fails, we return the image URL
        return jsonify({"imageUrl": image_url, "source_results": saucenao_results})

    except FileNotFoundError:
        # This specific FileNotFoundError is for the initial images folder check
        return jsonify({"error": f"Images folder not found on the server."}), 500 # Return a server error to the client
    except Exception as e:
        # Log any other unexpected errors in the main route logic
        print(f"An unexpected error occurred in get_random_image_and_source: {e}", flush=True)
        return jsonify({"error": f"An internal server error occurred: {e}"}), 500 # Return a server error to the client


if __name__ == '__main__':
    # This block is for running with Flask's development server directly.
    # In a production environment with Nginx and Gunicorn, this block is typically not executed.
    print("Running Flask development server...", flush=True)
    # Ensure the images folder exists for local testing
    if not os.path.exists(IMAGES_FOLDER_INTERNAL):
        os.makedirs(IMAGES_FOLDER_INTERNAL)
    # Use a production server like Gunicorn for deployment
    app.run(debug=True) # Set debug=False for production

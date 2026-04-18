import functions_framework
from google.cloud import firestore
from google import genai
from google.genai import types
import google.auth
import os
import requests

# Automatically detect Project ID
_, project_id = google.auth.default()

def get_region():
    """Fetches the region from the Google Cloud Metadata Server."""
    try:
        # The metadata server endpoint for the region
        url = "http://metadata.google.internal/computeMetadata/v1/instance/region"
        headers = {"Metadata-Flavor": "Google"}
        response = requests.get(url, headers=headers, timeout=2)
        if response.status_code == 200:
            # The response looks like 'projects/123456789/regions/us-central1'
            return response.text.split('/')[-1]
    except Exception as e:
        print(f"Metadata server unreachable: {e}")
    
    # Fallback to a default if metadata server fails (e.g., during local testing)
    return os.environ.get("CLOUD_RUN_REGION", "us-central1")

# 1. Initialize Clients
db = firestore.Client(project=project_id)
# Initialize the new Gen AI Client for Vertex AI
client = genai.Client(
    vertexai=True, 
    project=project_id, 
    location=get_region()
)

@functions_framework.http
def evening_can_slim_scout_job(request):
    try:
        clear_collection(db.collection('watchlist'))
        candidates = run_grounded_scan()
        
        for ticker, data in candidates.items():
            db.collection('watchlist').document(ticker).set(data)
            
        return f"Successfully updated {len(candidates)} candidates.", 200
    except Exception as e:
        print(f"Error: {str(e)}")
        return "Internal Server Error", 500

def run_grounded_scan():
    """Gemini 2.0 Flash O'Neil Scan using google-genai"""
    
    # Define the tool using the new SDK structure
    # Use types.GoogleSearch() for grounding
    search_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    prompt = """
    Perform a CAN SLIM scan. Identify 5-7 US stocks with:
    - Current Qtr Earnings > 25%
    - Annual Earnings Growth > 25% (3yr)
    - Relative Strength Rating > 80 (L)
    - Increasing Institutional Sponsorship
    
    Exclude stocks below the 50-day SMA.
    Return JSON format: {"TICKER": {"setup_type": "", "pivot_point": 0.0, "trading_plan": "", "conviction_commentary": ""}}
    """
    
    # The new SDK uses a unified generate_content call via the models attribute
    response = client.models.generate_content(
        model="gemini-2.0-flash", # Or gemini-1.5-flash
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[search_tool],
            response_mime_type="application/json" # Enforce JSON output
        )
    )

    # In the new SDK, response.text contains the generated string
    try:
        import json
        # Handle potential markdown formatting in the response
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        print(f"Failed to parse AI response: {e}")
        return {}

def clear_collection(coll_ref):
    docs = coll_ref.list_documents()
    batch = db.batch()
    for doc in docs:
        batch.delete(doc)
    batch.commit()

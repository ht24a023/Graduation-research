#!/usr/bin/env python3
import os
import json
import time
import requests

# Set DYNAMIC_ROUTING mode
os.environ['ROUTING_MODE'] = 'DYNAMIC_ROUTING'

# Wait for server to be ready
time.sleep(2)

# Test the consent flow
payload = {
    'message': 'アメリカの現在の大統領は誰ですか？',
    'session_id': 'test_search_fix_001'
}

print("Sending request to /chat endpoint...")
print(f"Payload: {payload}")
print()

try:
    response = requests.post('http://localhost:8000/chat', json=payload, timeout=30)
    print(f"Status Code: {response.status_code}")
    print()
    
    result = response.json()
    print("Response:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()
    
    # Check for search results in the UI
    if result.get('ui', {}).get('type') == 'cloud_api_consent':
        message = result.get('ui', {}).get('message', '')
        if '検索結果' in message or 'Wikipedia' in message:
            print("✓ Search results found in consent message!")
        else:
            print("✗ Search results NOT found in consent message")
    else:
        print(f"UI type: {result.get('ui', {}).get('type')}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

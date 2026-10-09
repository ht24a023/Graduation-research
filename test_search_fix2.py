#!/usr/bin/env python3
import json
import time
import requests

# Test the consent flow with a query that requires cloud API
# Use an open-ended question that local LLM might struggle with
test_queries = [
    {
        'id': '1',
        'message': '2024年の最新のAI技術の動向について説明してください',
        'name': 'Recent AI trends (requires current knowledge)'
    },
    {
        'id': '2', 
        'message': 'ChatGPT-4の最新の機能について教えてください',
        'name': 'GPT-4 latest features'
    },
    {
        'id': '3',
        'message': 'This query is intentionally hard for local LLM: What are the recent developments in quantum computing as of 2024?',
        'name': 'Quantum computing 2024'
    }
]

print("Testing consent flow with queries requiring cloud API...\n")

for test in test_queries:
    print(f"Test {test['id']}: {test['name']}")
    print(f"Message: {test['message']}")
    print()
    
    payload = {
        'message': test['message'],
        'session_id': f'test_consent_{test["id"]}'
    }
    
    try:
        response = requests.post('http://localhost:8000/chat', json=payload, timeout=30)
        result = response.json()
        
        print(f"Status: {response.status_code}")
        
        # Check for consent flow
        ui_type = result.get('ui', {}).get('type') if result.get('ui') else None
        
        if ui_type == 'cloud_api_consent':
            print("✓ Consent flow triggered!")
            message = result.get('ui', {}).get('message', '')
            if '検索結果' in message or 'Wikipedia' in message or '要約:' in message:
                print("  ✓ Search results found in message")
                # Print first 300 chars of message
                print(f"  Message preview: {message[:300]}...")
            else:
                print("  ✗ No search results in message")
        else:
            print(f"UI type: {ui_type}")
            route = result.get('evaluation', {}).get('route', 'unknown')
            print(f"Route used: {route}")
            response_text = result.get('response', '')
            print(f"Response: {response_text[:200]}...")
            
    except Exception as e:
        print(f"Error: {e}")
    
    print("-" * 60)
    print()

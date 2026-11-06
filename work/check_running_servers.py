import urllib.request,json
results=[]
for port in (8000,8001):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as response:data=json.load(response)
        results.append({'port':port,'reachable':True,'ok':data.get('ok')})
    except Exception as error:results.append({'port':port,'reachable':False,'error_type':type(error).__name__})
print(json.dumps(results))

from pathlib import Path
import tempfile,subprocess,json,time,sys,urllib.request,base64
R=Path(__file__).resolve().parents[1];O=R/'artifacts/workzone_03/bev_reconstruction/scene_bev';sys.path.insert(0,str(R.parents[1]/'dependencies/python'));import websocket
with tempfile.TemporaryDirectory(prefix='workzone1-bev-test-') as td:
 profile=Path(td)/'chrome';chrome=subprocess.Popen(['google-chrome','--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--disable-extensions','--no-proxy-server','--disable-background-networking','--password-store=basic','--remote-allow-origins=*','--remote-debugging-port=0',f'--user-data-dir={profile}','--window-size=1600,1100','http://127.0.0.1:8768/workzone3/bev'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);ws=None;seq=0
 try:
  for _ in range(100):
   if (profile/'DevToolsActivePort').exists():break
   time.sleep(.1)
  port=(profile/'DevToolsActivePort').read_text().splitlines()[0];tabs=json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list'));ws=websocket.create_connection(next(t for t in tabs if t['type']=='page')['webSocketDebuggerUrl'],timeout=30)
  def call(method,params={}):
   global seq
   seq+=1;ws.send(json.dumps({'id':seq,'method':method,'params':params}))
   while True:
    x=json.loads(ws.recv())
    if x.get('id')==seq:return x.get('result',{})
  def ev(code):
   x=call('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True})
   if 'exceptionDetails' in x:raise RuntimeError(x)
   return x['result'].get('value')
  for _ in range(100):
   try:
    if ev('typeof D!=="undefined" && document.querySelectorAll("#list tr").length>1'):break
   except Exception:pass
   time.sleep(.1)
  assert ev('D.counts.observations')==len(json.loads((R.parents[1]/'data/workzone_03/detections/final_detections.json').read_text())['observations'])
  ev('select(D.objects.find(o=>o.observation_ids.length>1).object_id,true)');assert ev('document.querySelectorAll("#detail [data-obs]").length')>1
  assert ev('document.querySelector("#detail img").complete')
  first=ev('selected');ev('document.querySelector("#detail [data-obs]:last-child").click()');assert ev('document.querySelector("#obs h4").textContent').startswith('W3_T')
  ev('$("stable").checked=true;$("stable").onchange()');assert ev('visible().length')==ev('D.counts.multi_frame_supported_objects')
  ev('$("class").value="road_work_ahead";$("class").onchange()');assert ev('visible().length')>0
  ev('$("class").value="all";$("stable").checked=false;table();reset()')
  old=ev('S');rect=ev('(()=>{let r=c.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()');call('Input.dispatchMouseEvent',{'type':'mouseWheel',**rect,'deltaX':0,'deltaY':-250});assert ev('S')>old
  ev('$("work").click()');shot=call('Page.captureScreenshot',{'format':'png'});(O/'browser_work_area.png').write_bytes(base64.b64decode(shot['data']))
  if ev('D.unresolved.length'):
   ev('$("search").value=D.unresolved[0].observation_id;$("find").click()');assert '未可靠定位' in ev('$("detail").textContent')
  assert ev('document.getElementById("roads")===null');assert ev('D.objects.every(o=>o.condition_status==="not_reassessed")')
  result={'load_final_observations':True,'object_selection_and_frame_switch':True,'stable_filter':True,'class_filter_road_work_ahead':True,'real_mouse_wheel_zoom':True,'unresolved_observation_search':True,'osm_removed':True,'human_review_writes':0}
  (O/'browser_validation.json').write_text(json.dumps(result,indent=2));print(result)
 finally:
  if ws:ws.close()
  chrome.terminate();chrome.wait(timeout=15)

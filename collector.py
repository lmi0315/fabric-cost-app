import json,re,urllib.request,datetime,pathlib,html
from html.parser import HTMLParser
ROOT=pathlib.Path(__file__).resolve().parent
URL='https://info.texnet.com.cn/list--20-.html'
class Reader(HTMLParser):
 def __init__(self): super().__init__();self.parts=[]
 def handle_data(self,data): self.parts.append(data)
 def text(self):return ' '.join(x.strip() for x in self.parts if x.strip())
MATERIALS={
 'polyester':('涤纶短纤',r'涤纶短纤'), 'spandex':('氨纶',r'氨纶'),
 'viscose':('粘胶短纤',r'粘胶短纤'), 'cotton':('皮棉',r'皮棉'),
 'nylon':('锦纶POY',r'锦纶POY')}
path=ROOT/'data'/'prices.json'
try: old=json.loads(path.read_text(encoding='utf-8'))
except: old={'updatedAt':None,'prices':{}}
prices=old.get('prices',{})
try:
 req=urllib.request.Request(URL,headers={'User-Agent':'Mozilla/5.0 (compatible; PersonalFabricCost/2.0; public-price-reader)'})
 with urllib.request.urlopen(req,timeout=25) as response: raw=response.read(1500000).decode('utf-8','replace')
 p=Reader();p.feed(raw); text=p.text()
 # Extract dated news headline; do not treat sidebar prices without dates as current.
 found=0
 for key,(name,pattern) in MATERIALS.items():
  matches=list(re.finditer(r'(\d{1,2})月(\d{1,2})日\s*'+pattern+r'(?:基准价)?(?:为|价格为|报)\s*(\d{3,7}(?:\.\d+)?)\s*(?:元/吨)?',text))
  for m in matches:
   month,day=int(m.group(1)),int(m.group(2));now=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
   year=now.year if month<=now.month+1 else now.year-1
   try: date=datetime.date(year,month,day)
   except ValueError: continue
   if date>now.date() or (now.date()-date).days>45:continue
   value=float(m.group(3));
   if not 3000<=value<=100000:continue
   prior=prices.get(key,{})
   if prior.get('date','')>=date.isoformat():break
   prices[key]={'name':name,'priceYuanPerKg':round(value/1000,4),'date':date.isoformat(),'source':'纺织网公开行情列表','sourceUrl':URL,'specification':name+'行业参考报价（不同规格可能存在差异）','status':'market'}
   found+=1;break
 print('Updated market prices:',found)
except Exception as exc: print('Collection unavailable, retaining dated observations:',str(exc))
# Reject future dates; preserve previously collected observations with original timestamps.
result={'updatedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'method':'public-web-headlines','prices':prices,'note':'公开网页报价，仅供参考；无日期或无法确认规格的价格不自动采信。'}
path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

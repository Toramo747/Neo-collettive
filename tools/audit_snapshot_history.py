#!/usr/bin/env python3
import json,re,subprocess,ipaddress
from collections import defaultdict
from datetime import datetime,timezone

TAGS=("v0.99.23","v0.99.27","v0.99.31")
TARGET="neo_latest_result.json"
MARKERS={"inbound_messages","agent_chat_events","inbound_review_queue","inbound_traffic_events","inbound_security_events"}
EMAIL=re.compile(r"(?i)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}")
PHONE=re.compile(r"(?<!\d)(?:\+?\d[\d .()/-]{6,}\d)(?!\d)")
NAME=re.compile(r"^[A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ'’-]{1,30}(?:[ -][A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ'’-]{1,30}){1,3}$")
IPV4=re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")
IPV6=re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])")
UA={"user_agent","user-agent","ua"}
THREAD={"thread_id","session_id","conversation_id","thread","session"}
PEER={"peer_id","agent_id","agent_uuid","peer_uuid","claimed_agent","sender_id"}
MSG={"message","message_text","content","body","prompt","input_text","text"}
RESP={"response","reply","answer","output_text","neo_response","response_text","reply_text"}
SEC={"security_excerpt","excerpt","security_summary","security_reason"}
NAMES={"name","display_name","sender_name","author_name","contact_name"}
CLOUD_WORDS=("cloud","hosting","datacenter","data center","vps","aws","amazon","azure","microsoft","google cloud","gcp","digitalocean","ovh","hetzner","linode","akamai","oracle cloud","alibaba cloud")

def git(*args):
 p=subprocess.run(["git",*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding="utf-8",errors="replace")
 return p.stdout if p.returncode==0 else ""

def walk(o,p=""):
 if isinstance(o,dict):
  for k,v in o.items():
   q=f"{p}.{k}" if p else str(k)
   if isinstance(v,(dict,list)): yield from walk(v,q)
   elif isinstance(v,str): yield q,v,o
 elif isinstance(o,list):
  for v in o: yield from walk(v,p)

def empty():
 return {k:set() for k in ("v4","v6","cloud","msg","resp","ua","thread","peer","sec","email","phone","name")}|{"keys":defaultdict(set)}

def extract_ips(s):
 out=set()
 for token in IPV4.findall(s)+IPV6.findall(s):
  try: out.add(str(ipaddress.ip_address(token)))
  except ValueError: pass
 return out

def cloud_context(parent):
 if not isinstance(parent,dict): return False
 text=" ".join(str(v).lower() for v in parent.values() if isinstance(v,(str,bool,int,float)))
 return any(w in text for w in CLOUD_WORDS)

def analyze(obj,sha,m):
 for kp,v,parent in walk(obj):
  leaf=kp.rsplit(".",1)[-1].lower(); low=kp.lower(); m["keys"][leaf].add(sha)
  for ip in extract_ips(v):
   m["v4" if ":" not in ip else "v6"].add(ip)
   if cloud_context(parent): m["cloud"].add(ip)
  m["email"].update(x.lower() for x in EMAIL.findall(v))
  for x in PHONE.findall(v):
   d=re.sub(r"\D","",x)
   if 7<=len(d)<=15:m["phone"].add(d)
  if leaf in NAMES and NAME.fullmatch(v.strip()):m["name"].add(v.strip())
  if leaf in UA or "user_agent" in leaf:m["ua"].add(v)
  if leaf in THREAD:m["thread"].add(v)
  if leaf in PEER or leaf.endswith("_agent_id") or leaf.endswith("_peer_id"):m["peer"].add(v)
  if leaf in SEC or ("security" in low and "excerpt" in leaf):m["sec"].add(v)
  if leaf in MSG and any(x in low for x in ("inbound","message","a2a","mcp","chat")):m["msg"].add(v)
  if leaf in RESP and any(x in low for x in ("neo","assistant","reply","response","chat")):m["resp"].add(v)

def merge(a,b):
 for k in ("v4","v6","cloud","msg","resp","ua","thread","peer","sec","email","phone","name"):a[k]|=b[k]
 for k,v in b["keys"].items():a["keys"][k]|=v

def counts(m):
 ips=m["v4"]|m["v6"]
 return {
  "ipv4_distinct":len(m["v4"]),"ipv6_distinct":len(m["v6"]),
  "ip_cloud_or_datacenter_offline":len(m["cloud"]),
  "ip_unclassified_offline":len(ips-m["cloud"]),
  "inbound_messages_distinct":len(m["msg"]),"neo_responses_distinct":len(m["resp"]),
  "user_agents_distinct":len(m["ua"]),"thread_session_ids_distinct":len(m["thread"]),
  "peer_agent_ids_distinct":len(m["peer"]),"security_excerpts_distinct":len(m["sec"]),
  "emails_distinct":len(m["email"]),"phones_distinct":len(m["phone"]),
  "possible_names_distinct_heuristic":len(m["name"])
 }

def load(ref,path):
 raw=git("show",f"{ref}:{path}")
 if not raw:return None
 try:return json.loads(raw)
 except Exception:return None

def path_at(ref):
 rows=git("ls-tree","-r","--name-only",ref).splitlines()
 x=[p for p in rows if p.rsplit("/",1)[-1].lower()==TARGET]
 return sorted(x)[0] if x else None

def tag_report(tag):
 p=path_at(tag)
 if not p:return {"present":False}
 o=load(tag,p)
 if o is None:return {"present":False}
 m=empty(); analyze(o,tag,m)
 return {"present":True,"counts":counts(m)}

def main():
 commits=[]
 for line in git("rev-list","--all","--timestamp").splitlines():
  p=line.split()
  if len(p)==2 and p[0].isdigit():
   commits.append((p[1],datetime.fromtimestamp(int(p[0]),timezone.utc).isoformat()))
 dates=dict(commits)

 paths=set()
 for line in git("rev-list","--objects","--all").splitlines():
  if " " not in line:continue
  _,path=line.split(" ",1); base=path.rsplit("/",1)[-1].lower()
  if base==TARGET or (path.lower().startswith("runtime/") and path.lower().endswith(".json")):paths.add(path)

 global_m=empty(); per={}; blobs=set(); seen_commits=set()
 for path in sorted(paths):
  for line in git("log","--all","--format=%H%x09%cI","--",path).splitlines():
   if "\t" not in line:continue
   sha,_=line.split("\t",1); obj=load(sha,path)
   if obj is None:continue
   if path.rsplit("/",1)[-1].lower()!=TARGET:
    if not isinstance(obj,(dict,list)):continue
    serialized=json.dumps(obj,sort_keys=True)
    if not any(f'"{k}"' in serialized for k in MARKERS):continue
   blob=git("rev-parse",f"{sha}:{path}").strip()
   if blob:blobs.add(blob)
   seen_commits.add(sha)
   m=per.setdefault(sha,empty()); analyze(obj,sha,m)

 for m in per.values():merge(global_m,m)

 finding_commits={}
 for label,key in (("email","email"),("phone","phone"),("possible_name","name"),("security_excerpt","sec")):
  rows=[]
  for sha,m in sorted(per.items()):
   if m[key]:
    rows.append({"commit":sha,"count":len(m[key]),"key_names":sorted(k for k,v in m["keys"].items() if sha in v)})
  finding_commits[label]=rows

 period=[dates[s] for s in seen_commits if s in dates]
 report={
  "scan_scope":{"rev_list_all":True,"reachable_commits":len(commits),"snapshot_versions_distinct":len(blobs),"snapshot_change_commits":len(seen_commits),"period_utc":{"first":min(period) if period else None,"last":max(period) if period else None}},
  "counts":counts(global_m),
  "finding_commits":finding_commits,
  "tags":{t:tag_report(t) for t in TAGS},
  "offline_cloud_classification_basis":"snapshot_context_metadata_only"
 }
 print(json.dumps(report,sort_keys=True,separators=(",",":")))

if __name__=="__main__":main()

#!/usr/bin/env python3

import subprocess
import re
import json

adapter = None
enclosure=None
slot=None

def yesno(state):
  states = {
    "No": 0
    }
  return states.get(state, 1)

def megacli(*args):
  """Run megacli, returning [] instead of raising if the controller lacks the
  feature (e.g. no BBU fitted). Keeps one missing section from killing the
  whole collector."""
  try:
    res = subprocess.run(['/usr/local/sbin/megacli'] + list(args),
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         check=True, universal_newlines=True)
    return res.stdout.splitlines()
  except (subprocess.CalledProcessError, OSError):
    return []

def isok(state, expected):
  return 1 if state == expected else 0

def state2int(state):
  #put remaining states here
  states = {
    "Online, Spun Up": 255,
    "JBOD": 255,
    "Hotspare, Spun Up": 256
    }

  return states.get(state, 0)

def tobytes(inp):
  suffix=['kb','mb','gb','tb']
  i=0;
  out=None
  inp=inp.strip().lower()

  while i < len(suffix):
    if re.search(suffix[i], inp):
      return float(inp.replace(suffix[i],'').strip()) * pow(1024,i+1)
    else:
      i+=1
  return inp

def main():
  info = subprocess.check_output(['/usr/local/sbin/megacli', '-AdpAllInfo', '-aAll', '-nolog']).decode('utf-8').splitlines()
  pdlist = subprocess.check_output(['/usr/local/sbin/megacli', '-PdList', '-aAll', '-nolog']).decode('utf-8').splitlines()
  encinfo = megacli('-EncInfo', '-aALL', '-nolog')
  prinfo = megacli('-AdpPR', '-Info', '-aALL', '-nolog')
  bbuinfo = megacli('-AdpBbuCmd', '-aALL', '-nolog')
  out = {}

  metrics= [
    'out["megacli_controller"]={ "help": "Controler information", "type": "gauge" , "metrics": []}',
    'out["megacli_controller_temperature_celsius"]={ "help": "ROC Temperature", "type": "gauge" , "metrics": []}',
    'out["megacli_memory_size_bytes"]={ "help": "Controler memory information", "type": "gauge" , "metrics": []}',
    'out["megacli_drives"]={ "help": "Drives information", "type": "gauge" , "metrics": []}',
    'out["megacli_memory_errors"]={ "help": "Memory errors", "type": "gauge" , "metrics": []}',
    'out["megacli_pd_info"]={ "help": "Physical drive detailed info", "type": "gauge" , "metrics": []}',
    'out["megacli_pd_temperature"]={ "help": "Physical drive temperature", "type": "gauge" , "metrics": []}',
    'out["megacli_pd_errors"]={ "help": "Physical drive error counters", "type": "gauge" , "metrics": []}',
    'out["megacli_pd_speed_bits"]={ "help": "Link and drive speed", "type": "gauge" , "metrics": []}',
    'out["megacli_enclosure_status_ok"]={ "help": "Enclosure status is Normal", "type": "gauge" , "metrics": []}',
    'out["megacli_patrol_read_auto"]={ "help": "Patrol read mode is Auto", "type": "gauge" , "metrics": []}',
    'out["megacli_bbu_state_ok"]={ "help": "Battery backup unit state is Optimal", "type": "gauge" , "metrics": []}',
    'out["megacli_bbu_soh_good"]={ "help": "Battery backup unit state of health is good", "type": "gauge" , "metrics": []}',
    'out["megacli_bbu_temperature_celsius"]={ "help": "Battery backup unit temperature", "type": "gauge" , "metrics": []}',
    'out["megacli_bbu_charge_percent"]={ "help": "Battery backup unit relative state of charge", "type": "gauge" , "metrics": []}',
    'out["megacli_bbu_capacity_mah"]={ "help": "Battery backup unit capacity", "type": "gauge" , "metrics": []}'
  ]

  pat_info = [
    { 
      'regex': re.compile('^Adapter\s+#\d+'),
      'action': [
        'global adapter; adapter=line.split("#")[1].strip()'
      ]
    },
    { 
      'regex': re.compile('^Product\s+Name\s+:'),
      'action': [
        'out["megacli_controller"]["metrics"].append({ "labels": { "adapter": adapter, "product_name": line.split(":")[1].strip()}, "val": 1})'
       ] 
    },
    { 
      'regex': re.compile('^FW\s+Package\s+Build\s*:'),
      'action': [
        'out["megacli_controller"]["metrics"].append({ "labels": { "adapter": adapter, "package_build": line.split(":")[1].strip()}, "val": 1 })'
       ]
    },
    { 
      'regex': re.compile('^FW\s+Version\s+:'),
      'action': [
        'out["megacli_controller"]["metrics"].append({ "labels": { "adapter": adapter, "firmware_version": line.split(":")[1].strip()}, "val": 1 })'
      ]
    },
    {
      'regex': re.compile('^BIOS\s+Version\s+:'),
      'action': [
        'out["megacli_controller"]["metrics"].append({ "labels": { "adapter": adapter, "bios_version": line.split(":")[1].strip()}, "val": 1 })'
      ]
    },
    {
      'regex': re.compile('^Memory\s+Size\s+:'),
      'action': [
        'out["megacli_memory_size_bytes"]["metrics"].append({ "labels": { "adapter": adapter, "type": "Total memory" }, "val": tobytes(line.split(":")[1].strip()) })'
      ]
    },
    {
      'regex': re.compile('^ROC\s+temperature\s+:\s+\d+'),
      'action': [
        'out["megacli_controller_temperature_celsius"]["metrics"].append({ "labels": { "adapter": adapter, "type": "ROC temperature" }, "val": line.split(":")[1].split()[0].strip() })'
      ]
    },
    {
      'regex': re.compile('^Current\s+Size\s+of\s+FW\s+Cache\s+:'),
      'action': [
        'out["megacli_memory_size_bytes"]["metrics"].append({ "labels": { "adapter": adapter, "type": "Write cache" }, "val": tobytes(line.split(":")[1].strip()) })'
      ]
    },
    {
      'regex': re.compile('^Virtual\s+Drives\s+:'),
      'action': [
        'out["megacli_drives"]["metrics"].append({ "labels": { "adapter": adapter, "type": "virtual", "state": "Total" }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^\s+Degraded\s+:'),
      'action': [
        'out["megacli_drives"]["metrics"].append({ "labels": { "adapter": adapter, "type": "virtual", "state": "Degraded" }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^\s+Offline\s+:'),
      'action': [
        'out["megacli_drives"]["metrics"].append({ "labels": { "adapter": adapter, "type": "virtual", "state": "Offline" }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^Physical\s+Devices\s+:'),
      'action': [
        'out["megacli_drives"]["metrics"].append({ "labels": { "adapter": adapter, "type": "physical", "state": "PhysicalTotal" }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^\s+Disks\s+:'),
      'action': [
        'out["megacli_drives"]["metrics"].append({ "labels": { "adapter": adapter, "type": "physical", "state": "DisksTotal"  }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^\s+Critical\s+Disks\s+:'),
      'action': [
        'out["megacli_drives"]["metrics"].append({ "labels": { "adapter": adapter, "type": "physical", "state": "Critical"  }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^\s+Failed\s+Disks\s+:'),
      'action': [
        'out["megacli_drives"]["metrics"].append({ "labels": { "adapter": adapter, "type": "physical", "state": "Failed"  }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^Memory\s+Correctable\s+Errors\s+:'),
      'action': [
        'out["megacli_memory_errors"]["metrics"].append({ "labels": { "adapter": adapter, "type": "correctable"  }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^Memory\s+Uncorrectable\s+Errors\s+:'),
      'action': [
        'out["megacli_memory_errors"]["metrics"].append({ "labels": { "adapter": adapter, "type": "uncorrectable"  }, "val": line.split(":")[1].strip() })'
      ]
    },
  ]
  

  position=None
  device_id=None
  wwn=None
  
  pat_pd = [
    {
      'regex': re.compile('^Adapter\s+#\d+'),
      'action': ['global adapter; adapter=line.split("#")[1].strip()']
    },
    {
      'regex': re.compile('^Enclosure\s+Device\s+ID:'),
      'action': ['global enclosure; enclosure=line.split(":")[1].strip()']
    },
    {
      'regex': re.compile('^Slot\s+Number\s*:'),
      'action': ['global slot; slot=line.split(":")[1].strip()']
    },
    {
      'regex': re.compile('^Drive\'s\s+position:'),
      'action': [
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "disk_group"}, "val": line.split(":")[2].split(",")[0].strip() })',
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "span"}, "val": line.split(":")[3].split(",")[0].strip() })',
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "arm"}, "val": line.split(":")[4].split(",")[0].strip() })'
      ]
    },
    {
      'regex': re.compile('^Device\s+Id\s*:'),
      'action': [
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "device_id" }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^WWN\s*:'),
      'action': [
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "wwn" }, "val": int(line.split(":")[1].strip(), 16) })'
      ]
    },
    {
      'regex': re.compile('^Sequence\s+Number\s*:'),
      'action': [
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "sequence_number" }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^Media\s+Error\s+Count\s*:'),
      'action': [
        'out["megacli_pd_errors"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "media" }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^Other\s+Error\s+Count\s*:'),
      'action': [
        'out["megacli_pd_errors"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "other" }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^Predictive\s+Failure\s+Count\s*:'),
      'action': [
        'out["megacli_pd_errors"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "predictive" }, "val": line.split(":")[1].strip() })'
      ]
    },
    {
      'regex': re.compile('^Raw\s+Size\s*:'),
      'action': [
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "size_raw" }, "val": tobytes(line.split(":")[1].split("[")[0].strip()) })'
      ]
    },
    {
      'regex': re.compile('^Non\s+Coerced\s+Size\s*:'),
      'action': [
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "size_non_coerced" }, "val": tobytes(line.split(":")[1].split("[")[0].strip()) })'
      ]
    },
    {
      'regex': re.compile('^Coerced\s+Size\s*:'),
      'action': [
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "size_coerced" }, "val": tobytes(line.split(":")[1].split("[")[0].strip()) })'
      ]
    },
    {
      'regex': re.compile('^Firmware\s+state\s*:'),
      'action': [
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "state" }, "val": state2int(line.split(":")[1].strip()) })'
      ]
    },
    {
      'regex': re.compile('^Connected\s+Port\s+Number\s*:'),
      'action': [
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "port" }, "val": line.split(":")[1].split("(")[0].strip() })',
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "path" }, "val": line.split("path")[1].split(")")[0].strip() })'
      ]
    },
    {
      'regex': re.compile('^Needs\s+EKM\s+Attention\s*:'),
      'action': [
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "ekm_attention_needed" }, "val": yesno(line.split(":")[1].strip()) })'
      ]
    },
    {
      'regex': re.compile('^Device\s+Speed\s*:'),
      'action': [
        'out["megacli_pd_speed_bits"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "drive" }, "val": tobytes(line.split(":")[1].split("/")[0].strip()) })'
      ]
    },
    {
      'regex': re.compile('^Link\s+Speed\s*:'),
      'action': [
        'out["megacli_pd_speed_bits"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "link" }, "val": tobytes(line.split(":")[1].split("/")[0].strip()) })'
      ]
    },
    {
      'regex': re.compile('^Drive\s+Temperature\s*:\d{1,2}C'),
      'action': [
        'out["megacli_pd_temperature"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "celsius" }, "val": line.split(":")[1].split("C")[0].strip() })',
        # 'out["megacli_pd_temperature"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "barbarians" }, "val": line.split("(")[1].split(" ")[0].strip() })'
      ]
    },
    {
      'regex': re.compile('^Drive\s+has\s+flagged\s+a\s+S.M.A.R.T\s+alert\s*:'),
      'action': [
        'out["megacli_pd_info"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enclosure, "slot": slot, "type": "smart_alert" }, "val": yesno(line.split(":")[1].strip()) })'
      ]
    },
  ]
  
  pat_enc = [
    {
      'regex': re.compile(r'^\s*Number\s+of\s+enclosures\s+on\s+adapter'),
      'action': ['global adapter; adapter=line.split("adapter")[1].split("--")[0].strip()']
    },
    {
      'regex': re.compile(r'^\s*Device\s+ID\s*:'),
      'action': ['global enc_id; enc_id=line.split(":")[1].strip()']
    },
    {
      'regex': re.compile(r'^\s+Status\s*:'),
      'action': [
        'out["megacli_enclosure_status_ok"]["metrics"].append({ "labels": { "adapter": adapter, "enclosure": enc_id, "status": line.split(":")[1].strip() }, "val": isok(line.split(":")[1].strip(), "Normal") })'
      ]
    },
  ]

  pat_pr = [
    {
      'regex': re.compile(r'^Adapter\s+\d+:\s+Patrol\s+Read\s+Information'),
      'action': ['global adapter; adapter=line.split(":")[0].split()[1].strip()']
    },
    {
      'regex': re.compile(r'^Patrol\s+Read\s+Mode\s*:'),
      'action': [
        'out["megacli_patrol_read_auto"]["metrics"].append({ "labels": { "adapter": adapter, "mode": line.split(":")[1].strip() }, "val": isok(line.split(":")[1].strip(), "Auto") })'
      ]
    },
  ]

  pat_bbu = [
    {
      'regex': re.compile(r'^BBU\s+status\s+for\s+Adapter\s*:'),
      'action': ['global adapter; adapter=line.split(":")[1].strip()']
    },
    {
      'regex': re.compile(r'^Battery\s+State\s*:'),
      'action': [
        'out["megacli_bbu_state_ok"]["metrics"].append({ "labels": { "adapter": adapter, "state": line.split(":")[1].strip() }, "val": isok(line.split(":")[1].strip(), "Optimal") })'
      ]
    },
    {
      'regex': re.compile(r'^isSOHGood\s*:'),
      'action': [
        'out["megacli_bbu_soh_good"]["metrics"].append({ "labels": { "adapter": adapter }, "val": yesno(line.split(":")[1].strip()) })'
      ]
    },
    {
      'regex': re.compile(r'^Temperature\s*:\s*\d+\s*C'),
      'action': [
        'out["megacli_bbu_temperature_celsius"]["metrics"].append({ "labels": { "adapter": adapter }, "val": line.split(":")[1].split("C")[0].strip() })'
      ]
    },
    {
      'regex': re.compile(r'^Relative\s+State\s+of\s+Charge\s*:'),
      'action': [
        'out["megacli_bbu_charge_percent"]["metrics"].append({ "labels": { "adapter": adapter }, "val": line.split(":")[1].split("%")[0].strip() })'
      ]
    },
    {
      'regex': re.compile(r'^Remaining\s+Capacity\s*:'),
      'action': [
        'out["megacli_bbu_capacity_mah"]["metrics"].append({ "labels": { "adapter": adapter, "type": "remaining" }, "val": line.split(":")[1].split("mAh")[0].strip() })'
      ]
    },
    {
      'regex': re.compile(r'^Full\s+Charge\s+Capacity\s*:'),
      'action': [
        'out["megacli_bbu_capacity_mah"]["metrics"].append({ "labels": { "adapter": adapter, "type": "full_charge" }, "val": line.split(":")[1].split("mAh")[0].strip() })'
      ]
    },
  ]

  for m in metrics:
    exec(m)

  for line in info: 
    for p in pat_info:
      if p['regex'].match(line):
        for a in p['action']:
          exec(a)
        continue

  for line in pdlist:
    for p in pat_pd:
      if p['regex'].match(line):
        for a in p['action']:
          exec(a)
        continue

  for src, pats in ((encinfo, pat_enc), (prinfo, pat_pr), (bbuinfo, pat_bbu)):
    for line in src:
      for p in pats:
        if p['regex'].match(line):
          for a in p['action']:
            exec(a)
          continue

#  print json.dumps(out, indent=2, sort_keys=True)
  for k,v in out.items():
    print("# HELP " + k + " " + v['help'])
    print("# TYPE " + k + " " + v['type'])
    for m in v['metrics']:
      print ( str(k) + '{' + ', '.join([ "{}=\"{}\"".format(str(l),str(m['labels'][l])) for l in sorted(m['labels']) ]) + '} ' +  str(m['val']) )

if __name__ == "__main__":
  main()

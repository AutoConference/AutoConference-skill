"""Synthetic integration fixture only; never a sleep-staging benchmark."""
import json
from pathlib import Path
import numpy as np

folder=Path(__file__).resolve().parent
targets=[folder/f'{split}.npz' for split in ('train','validation','test')]+[folder/'schedule.json']
if any(p.exists() for p in targets):
    raise SystemExit('Fixture output already exists; use an empty copy of this example directory.')
rng=np.random.default_rng(20261120)
t=np.arange(3000)/100
for split,n in [('train',50),('validation',20),('test',20)]:
    labels=np.arange(n)%5
    x=np.array([10*np.sin(2*np.pi*(1+label)*t)+rng.normal(0,1,3000) for label in labels],dtype='float32')
    data={'x':x,'subject':np.full(n,split),'sample_id':np.array([f'{split}-{i}' for i in range(n)]),
          'sfreq_hz':np.array(100),'unit':np.array('uV')}
    if split!='test': data['y']=labels.astype('int64')
    np.savez(folder/f'{split}.npz',**data)
schedule={'schema_version':1,'n_train':50,'batch_size':16,'model_init':1729,
          'minibatch':[100+i for i in range(3)],'dropout':[[1000+i*4+b for b in range(4)] for i in range(3)]}
(folder/'schedule.json').write_text(json.dumps(schedule,indent=2),encoding='utf-8')
print('Created synthetic fixture inputs; no real EEG or performance claim.')

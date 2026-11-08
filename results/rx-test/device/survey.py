import sys, numpy as np
from scipy.io import wavfile
from scipy import signal
sys.path.insert(0, "."); import analyze_rx as A
for f in sys.argv[1:]:
    fs,x=wavfile.read(f); x=x.astype(float)/32768
    if x.ndim==1: x=x[:,None]
    for c in range(x.shape[1]):
        v=x[:,c]-x[:,c].mean()
        if not v.any(): print(f"{f.split('/')[-1]:34s} ch{c} all zero"); continue
        fr,P=signal.welch(v,fs,nperseg=4096); df=fr[1]-fr[0]
        bp=lambda a,b:10*np.log10(P[(fr>a)&(fr<b)].sum()*df+1e-20)
        z=np.convolve(v,A.RRC,'same'); q=z**2-np.mean(z**2)
        Q=np.abs(np.fft.rfft(q*np.hanning(len(q)))); fq=np.fft.rfftfreq(len(q),1/fs)
        m=(fq>4700)&(fq<4900); i=np.argmax(Q*m); line=20*np.log10(Q[i]/np.median(Q[m]))
        print(f"{f.split('/')[-1]:34s} ch{c} rms {20*np.log10(v.std()):6.1f} dBFS pk {20*np.log10(np.abs(v).max()):6.1f} | 50-300 {bp(50,300):6.1f} 300-3k {bp(300,3000):6.1f} 3-6k {bp(3000,6000):6.1f} >8k {bp(8000,20000):6.1f} | clk {fq[i]:.1f} Hz {line:5.1f} dB")

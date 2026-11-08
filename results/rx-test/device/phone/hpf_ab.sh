cd /data/local/tmp; M="./tinymix -D 0"; DBG=/sys/kernel/debug/mtksocaudio
con0() { cat $DBG | grep "^AFE_ADDA_UL_SRC_CON0 " | sed 's/.*= //'; }
./btmode 1; sleep 1; $M set Audio_ADC_1_Switch On; $M set Audio_Preamp1_Switch IN_ADC1
./tinycap rx/hpf_ab.wav -D 0 -d 1 -c 2 -r 48000 -b 16 -t 20 >/dev/null 2>&1 &
CAP=$!; sleep 2
V=$(con0); echo "t=2 dump CON0=$V"
dmesg -c >/dev/null 2>&1; echo "Getafereg,0x0114" > $DBG; sleep 0.2; echo "Getafereg dmesg: $(dmesg | grep -iE "regaddr|0x114|afereg" | tail -2)"
VD=$((V)); if [ $((VD & 0x400)) -eq 0 ]; then echo "ABORT: bit10 not set"; else
  sleep 6; NEW=$(printf "0x%x" $((VD & ~0x400))); echo "t=8 Setafereg,0x0114,$NEW"; echo "Setafereg,0x0114,$NEW" > $DBG; sleep 0.2; echo "readback CON0=$(con0)"
  sleep 9; echo "t=17 restore Setafereg,0x0114,$V"; echo "Setafereg,0x0114,$V" > $DBG; sleep 0.2; echo "readback CON0=$(con0)"; fi
wait $CAP; echo "cap done"
$M set Audio_Preamp1_Switch OPEN; $M set Audio_ADC_1_Switch Off; ./btmode 0; $M contents > rx/tinymix-after-hpf.txt; echo "idle CON0=$(con0)"

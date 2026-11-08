# usage: sh cap.sh name seconds   -- BT mode + ADC1/IN_ADC1 capture, then full restore
cd /data/local/tmp; M="./tinymix -D 0"
./btmode 1 >/dev/null; sleep 1; $M set Audio_ADC_1_Switch On; $M set Audio_Preamp1_Switch IN_ADC1
timeout $(($2+10)) ./tinycap rx/$1.wav -D 0 -d 1 -c 2 -r 48000 -b 16 -t $2 >/dev/null 2>&1; echo "cap $1 rc=$?"
$M set Audio_Preamp1_Switch OPEN; $M set Audio_ADC_1_Switch Off; ./btmode 0 >/dev/null

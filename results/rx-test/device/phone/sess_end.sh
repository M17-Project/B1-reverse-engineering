cd /data/local/tmp; M="./tinymix -D 0"
$M set Audio_Preamp1_Switch OPEN; $M set Audio_ADC_1_Switch Off; ./btmode 0 >/dev/null; $M contents > rx/tinymix-after-$1.txt; echo "session end $(date +%T)"

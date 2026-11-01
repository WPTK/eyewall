# shared helpers; source me
: "${OUT:=$PWD/out}"; mkdir -p "$OUT"
log(){ echo "[$(date +%T)] $*" | tee -a "$OUT/steps.log"; }
run(){ echo "\$ $*"; "$@"; echo "rc=$?"; }

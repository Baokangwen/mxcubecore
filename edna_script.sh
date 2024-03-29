. blissrc
#echo "Sleeping 30s in order to allow images to be written to disk, please wait..."
#sleep 30
echo "Running edna --inputFile $1 --outputFile $2 --basedir $3"
echo " EDNA_SITE= $EDNA_SITE (an example is ESRF_ID14EH1. If not then please check BLISS_ENV_VAR"
ednaStartScriptFileName=$3/edna_start_$(date +"%Y%m%d_%H%M%S_%N").sh
echo "Name of EDNA startup script: $ednaStartScriptFileName"
# echo "export EDNA_SITE=$EDNA_SITE" > $ednaStartScriptFileName
echo "/opt/edna2/bin/run_edna2.py --inputFile $1 --outputFile $2 --basedir $3 2>&1" >> $ednaStartScriptFileName
chmod a+x $ednaStartScriptFileName
ednanormalhost=bl19uenda

ssh $ednanormalhost $ednaStartScriptFileName

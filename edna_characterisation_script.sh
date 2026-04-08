#. blissrc
#echo "Sleeping 30s in order to allow images to be written to disk, please wait..."
#sleep 30
echo "Running edna plugin launcher EDPluginControlAutoPROCv1 --inputFile $1 --outputFile $2 --basedir $3"
ednaStartScriptFileName=$3/edna_start_$(date +"%Y%m%d_%H%M%S_%N").sh
echo "Name of EDNA startup script: $ednaStartScriptFileName"
echo "export EDNA_SITE=SSRF_BL19U1" > $ednaStartScriptFileName
# EDPluginControlAutoPROCv1.0 and EDPluginControlEDNAprocv1_0
echo "/home/edna/app/edna-mx/kernel/bin/edna-plugin-launcher  --execute EDPluginControlCharacterisationv1.6 --inputFile $1 --outputFile $2 --basedir $3 2>&1" >> $ednaStartScriptFileName
chmod a+x $ednaStartScriptFileName
#cat $ednaStartScriptFileName
# Recuperate the name of the MX processing computer...
ednanormalhost=edna

ssh $ednanormalhost $ednaStartScriptFileName


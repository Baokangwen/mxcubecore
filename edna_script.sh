#. blissrc
#sleep 30
taskname=Characterisation
echo "Running edna --inputFile $1 --outputFile $2 --basedir $3"
ednaStartScriptFileName=$3/edna_start_$(date +"%Y%m%d_%H%M%S_%N").sh
echo "Name of EDNA startup script: $ednaStartScriptFileName"
#echo "/opt/edna2/bin/run_edna2.py --inputFile $1 --outputFile $2 --basedir $3 2>&1" >> $ednaStartScriptFileName
echo "/opt/edna2/bin/run_edna2.py --taskName $taskname --inDataFile $1 --outDataFile $2" >> $ednaStartScriptFileName
chmod a+x $ednaStartScriptFileName
ednanormalhost=bl19uedna

ssh root@$ednanormalhost $ednaStartScriptFileName

echo "END"

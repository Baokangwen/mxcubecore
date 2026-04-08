#. blissrc
#sleep 30
echo "Running edna --inputFile $1 --outputFile $2 --basedir $3 --taskName $4"
#taskname=$4
ednaStartScriptFileName=$3/edna_start_$(date +"%Y%m%d_%H%M%S_%N").sh
echo "Name of EDNA startup script: $ednaStartScriptFileName"
#echo "/opt/edna2/bin/run_edna2.py --inputFile $1 --outputFile $2 --basedir $3 2>&1" >> $ednaStartScriptFileName
echo "#!/bin/bash" >> $ednaStartScriptFileName
#echo "conda init bash" >> $ednaStartScriptFileName
echo "source /home/demo/anaconda3/bin/activate edna2" >> $ednaStartScriptFileName
echo "/opt/edna2/bin/run_edna2.py --taskName $4 --inDataFile $1 --outDataFile $2" >> $ednaStartScriptFileName
chmod a+x $ednaStartScriptFileName
ednanormalhost=bl19uedna2

ssh demo@$ednanormalhost $ednaStartScriptFileName

echo "END"

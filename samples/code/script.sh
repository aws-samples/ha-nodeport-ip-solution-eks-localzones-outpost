#!/bin/sh
cd /app
echo secondary ip for Nodeport $1
python3 -u assign-secondary-ip.py "$@"
while (1)
do
	sleep 60
done	

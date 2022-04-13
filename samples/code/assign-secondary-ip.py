#!/usr/bin/env python3
# -----------------------------------------------------------
#// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#// SPDX-License-Identifier: MIT-0
# This code demonstrates how to automate the secondary IP allocation on on the AWS EKS worker node ENI 
# author: Raghvendra Singh
# -----------------------------------------------------------
import requests
import boto3, json
import sys, datetime
import netaddr
from netaddr import *
from requests.packages.urllib3 import Retry
import subprocess,copy,time
from collections import defaultdict
from multiprocessing import Process

## Logs are printed with timestamp as an output for kubectl logs of this container 
def tprint(var):
    print (datetime.datetime.now(),"-",var)
    
# This function, Finds the ENIs, for a list of given ipv6 secondary IPs 
# If an ENI is found, then the IPs are unassigned from that ENI 
def release_ipv6(ip6List,subnet_cidr,client):
    tprint("Going to release ip6List: " + str(ip6List))     
    
    response = client.describe_network_interfaces(
        Filters=[
            {
                'Name': 'ipv6-addresses.ipv6-address',
                'Values': ip6List
            },
        ],
    )
    if response['NetworkInterfaces'] == []:
        tprint("ENI of ipv6 not attached yet, no need to release")
    else:
        for j in response['NetworkInterfaces']:
            network_interface_id = j['NetworkInterfaceId']
            response = client.unassign_ipv6_addresses(
                Ipv6Addresses=ip6List,
                NetworkInterfaceId = network_interface_id
            )
    tprint("Finished releasing ip6List: " + str(ip6List))     

## This function, assigns/moves the list of secondary ipv4 addresses to the given ENI  
#  The AllowReassignment flag = True , enables the force move of secondary ip addresses f=if they are assigned to soem other ENI  
#  If there are any error, Exception is thrown which is handled in the main block.    
def assign_ip_to_nic(ipList,network_interface_id,client):  
    tprint("Going to reassign iplist: " + str(ipList) + " to ENI:" +network_interface_id )    

    response = client.assign_private_ip_addresses(
        AllowReassignment=True,
        NetworkInterfaceId=network_interface_id,
        PrivateIpAddresses = ipList    
        )
    
## This function, assigns the list of secondary ipv6 addresses to the given ENI  
#  If there are any error, Exception is thrown which is handled in the main block          
def assign_ip6_to_nic(ip6List,network_interface_id,client):  
    tprint("Going to assign ip6List: " + str(ip6List) + " to ENI:" +network_interface_id )     
    response = client.assign_ipv6_addresses(
        Ipv6Addresses=ip6List,
        NetworkInterfaceId=network_interface_id,
        )
## This function gets the metadata token
def get_metadata_token():
    token_url="http://169.254.169.254/latest/api/token"
    headers = {'X-aws-ec2-metadata-token-ttl-seconds': '21600'}
    r= requests.put(token_url,headers=headers,timeout=(2, 5))
    return r.text

def get_instance_id():
    instance_identity_url = "http://169.254.169.254/latest/dynamic/instance-identity/document"
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=0.3)
    metadata_adapter = requests.adapters.HTTPAdapter(max_retries=retries)
    session.mount("http://169.254.169.254/", metadata_adapter)
    try:
        r = requests.get(instance_identity_url, timeout=(2, 5))
        code=r.status_code
        if code == 401: ###This node has IMDSv2 enabled, hence unauthorzied, we need to get token first and use the token
            tprint("node has IMDSv2 enabled!! Fetching Token first")
            token=get_metadata_token()
            headers = {'X-aws-ec2-metadata-token': token}
            r = requests.get(instance_identity_url, headers=headers, timeout=(2, 5))
            code=r.status_code
        if code == 200:
            response_json = r.json()
            instanceid = response_json.get("instanceId")
            region = response_json.get("region")
            return(instanceid,region)
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as err:
        tprint("Execption: Connection to AWS EC2 Metadata timed out: " + str(err.__class__.__name__))
        tprint("Execption: Is this an EC2 instance? Is the AWS metadata endpoint blocked? (http://169.254.169.254/)")
        raise
    except Exception as e:
        tprint("Execption: caught exception " + str(e.__class__.__name__))
        raise             
## This function fetches the subnet CIDR for the given subnet
# All exceptions handled in the main function
def get_subnet_cidr(ec2_client,subnetId):
    response = ec2_client.describe_subnets(
        SubnetIds=[
            subnetId,
        ],    
    )
    for i in response['Subnets']:
        CidrBlock = i['CidrBlock']
    return  CidrBlock

## This function collects the details of each ENI attached to the worker node and corrresponding subnet IDs
# later it fetches the subnetCIDR for the given subnet ID and stores them in a Dictionary where key is the CidrBlock and value is the ENI id
# All exceptions handled in the main function
def get_instanceDetails(ec2_client,instance_id,instanceData):
    response = ec2_client.describe_instances(
        InstanceIds= [ instance_id ]
    )
    for r in response['Reservations']:
      for i in r['Instances']:
        for j in i["NetworkInterfaces"]:
            cidrBlock = get_subnet_cidr(ec2_client,j["SubnetId"])
            if cidrBlock not in instanceData:
                instanceData[cidrBlock] = j["NetworkInterfaceId"]
                tprint("Node ENIC: "+ j["NetworkInterfaceId"] + " cidr: " + cidrBlock  + " subnetID: " + j["SubnetId"])
            else:
                tprint("Ignoring duplicate subnet Node ENIC: "+ j["NetworkInterfaceId"] + " cidr: " + cidrBlock  + " subnetID: " + j["SubnetId"])

def main():    
    instance_id = None
    region= None
    instanceData = {}
    ips=[]
    ec2_client=None
    print(sys.argv)
    if len(sys.argv) >1 :
        ips=sys.argv[1:]
    else:
        tprint("No IPs passed, exiting")    
    while (1) :
        retCode=0
        try:
            ipmap = defaultdict(list)
            ip6map = defaultdict(list)
            # at the very first iteration, get the instance ID of the underlying worker & create a boto3 ec2 client to get instance data attached ENIs and corresponding subnet IP CIDRblocks 
            if not instance_id :
                data = get_instance_id()
                instance_id = data[0]
                region = data[1]
                tprint ("Got InstanceId: " + instance_id + " region: " + region)  
                ec2_client = boto3.client('ec2', region_name=region)
                get_instanceDetails(ec2_client,instance_id,instanceData)
            # Tn this code block, for the IPs passed via arguements to the script, we are creating a Map/dictionary where subnet network cidr is the key and actual ip addressesis the value 
            for ipaddress in ips: 
                ip = IPNetwork(ipaddress)
                cidr = str(ip.cidr)
                if  netaddr.valid_ipv4(str(ip.ip)):                  
                    ipmap[cidr].append(str(ip.ip))
                else :
                    ip6map[cidr].append(str(ip.ip))
            for cidr in ipmap:
                assign_ip_to_nic(ipmap[cidr],instanceData[cidr],ec2_client)   
                tprint ("Finished all IPV4: "+str(ipmap[cidr]))            
            for cidr6 in ip6map:
                release_ipv6(ip6map[cidr6],cidr6,ec2_client)
                assign_ip6_to_nic(ip6map[cidr6],instanceData[cidr6],ec2_client)  
                tprint ("Finished all IPV6: "+str(ip6map[cidr]))                                
            tprint ("Exiting after successful execution")  
            exit(0)                     
        # If there are any exceptions in ip assignment to the NICs then catch it using catch all exception and keep trying & logging untill the problem is resolved
        except (Exception) as e:
            tprint ("Exception :" + str(e))     
            tprint ("continuing the handling")
        time.sleep(2)    

if __name__ == "__main__":
    main()


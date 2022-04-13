
## High Available Secondary IP NodePort Solution

## Container Based solution alongwith EC2 userdata


### Pre-requisite

1. EKS cluster
2. EKS nodegroup (with desired IAM role & [IAM policy](samples/iam-policy.json).
6. Bastion node with docker and git

### How to Build

Clone this repo:

```
https://github.com/aws-samples/ha-nodeport-ip-solution-eks-localzones-outpost
```

Please replace the xxxxxxxxx with your accout id and also choose the region where your ECR repository is.
```
docker build —tag xxxxxxxxx.dkr.ecr.us-east-2.amazonaws.com/assign-secondary-ip:0.1 .
aws ecr get-login-password --region us-east-2 | docker login --username AWS --password-stdin xxxxxxxxx.dkr.ecr.us-east-2.amazonaws.com
aws ecr create-repository --repository-name aws-ip-manager --region us-east-2
docker push xxxxxxxxx.dkr.ecr.us-east-2.amazonaws.com/assign-secondary-ip:0.1
```

###  Setup the aws-node deployment to not exceed the max secondary IP on the ENI

Please set the MINIMUM_IP_TARGET and WARM_IP_TARGET variable according to the instance type, so that total of both is at least 1-2 less than the max IP addresses supported per ENI on that instance type. This is needed so that our HA NodePort IP can be 

Ex:
```
kubectl set env daemonset aws-node -n kube-system MINIMUM_IP_TARGET=10 WARM_IP_TARGET=2
kubectl -n kube-system describe ds aws-node | grep -i TARGET
```
Sample output:

WARM_ENI_TARGET: 1
WARM_IP_TARGET: 2
MINIMUM_IP_TARGET: 10

###  Create the NodeGroup with the static IP in userdata
Create the nodegroup using CloudFormation. For the EC2 userdata, Replace xxxxxxxx with eks cluster name , 10.0.0.201/24 is the HA nodeport IP for the cluster, change it as per your subnets. yyyyyyyy is the cloudformation stack name. Nodeselector cnf=test is just an example, feel free to remove or chnage from below and the Deployment spec. 

```
#!/bin/bash
set -o xtrace
NODEPORT_IP="10.0.0.201/24"
ip address add ${NODEPORT_IP} dev eth0 >> /etc/rc.d/rc.local
chmod +x /etc/rc.d/rc.local
systemctl enable rc-local
systemctl start rc-local
/etc/eks/bootstrap.sh xxxxxxxxx —use-max-pods false —kubelet-extra-args '—node-labels=cnf=test’
/opt/aws/bin/cfn-signal —exit-code $? \
--stack yyyyyyyy \
--resource NodeGroup \
--region us-east-2
```

### Configure & Deploy Floating NodePort IP Helper Deployment

Floating NodePort IP management container, is a deployment with single replica. This deployment will take the pre-selected IP as a parameter to configure this secondary Ip on the workers primary interface. 

```
cat nodeport-helper.yaml | tail -9
```
sample o/p:

      containers:
      - name: nodeport-helper
        image: 903666168365.dkr.ecr.us-east-2.amazonaws.com/assign-secondary-ip:0.1
        imagePullPolicy: Always
        env:
        - name: NODEPORT_IP
          value: "10.0.0.201/24"
        args: [/bin/sh, -c, '/app/script.sh']

Deploy the nodeport-helper deployment

```
$ kubectl apply -f nodeport-helper-deployment.yaml
deployment.apps/nodeport-helper-deploy created
$ kubectl get po
NAME READY STATUS RESTARTS AGE
nodeport-helper-deploy-5b98c7b65c-mxczx 1/1 Running 0 14s
$ kubectl logs nodeport-helper-deploy-5b98c7b65c-mxczx
secondary ip for Nodeport 10.0.0.201/24
['assign-secondary-ip.py', '10.0.0.201/24']
2022-04-12 03:55:34.249750 - node has IMDSv2 enabled!! Fetching Token first
2022-04-12 03:55:34.253026 - Got InstanceId: i-04604bd4c1b99d0b8 region: us-east-2 privateIp: 10.0.0.179
2022-04-12 03:55:34.463567 - Going to reassign iplist: ['10.0.0.201'] to ENI:eni-060d7c8455fafc513
2022-04-12 03:55:34.878863 - Finished secondary IPV4 assignment: 10.0.0.201
2022-04-12 03:55:34.878900 - Exiting after successful execution
$ kubectl apply -f sample-deployment-nginx.yaml
deployment.apps/nginx-deployment created
$ kubectl apply -f sample-nodeportservice.yaml
service/mynginxsvc created
$ kubectl get po
NAME READY STATUS RESTARTS AGE
nginx-deployment-5b8766fc49-82zmh 1/1 Running 0 34s
nginx-deployment-5b8766fc49-wmbvk 1/1 Running 0 34s
nodeport-helper-deploy-5b98c7b65c-mxczx 1/1 Running 0 1m5s
$
```

### Verify access is working with this HA Nodeport IP
```
$ curl 10.0.0.201:30180
<!DOCTYPE html>
<html>
<head>
<title>Welcome to nginx!</title>
<style>
    body {
        width: 35em;
        margin: 0 auto;
        font-family: Tahoma, Verdana, Arial, sans-serif;
    }
</style>
</head>
<body>
<h1>Welcome to nginx!</h1>
<p>If you see this page, the nginx web server is successfully installed and
working. Further configuration is required.</p>

<p>For online documentation and support please refer to
<a href="http://nginx.org/">nginx.org</a>.<br/>
Commercial support is available at
<a href="http://nginx.com/">nginx.com</a>.</p>

<p><em>Thank you for using nginx.</em></p>
</body>
</html>
$ kubectl get po -o wide | grep -i nodeport
nodeport-helper-deploy-5b98c7b65c-mxczx   1/1     Running     0          5m33s   10.0.0.71    ip-10-0-0-15.us-east-2.compute.internal    <none>           <none>
```

## Cleanup
```
$ kubectl delete -f sample-nodeportservice.yaml
service "mynginxsvc" deleted
$ kubectl delete -f sample-deployment-nginx.yaml
deployment.apps "nginx-deployment" deleted
$ kubectl delete -f nodeport-helper-deployment.yaml
```

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

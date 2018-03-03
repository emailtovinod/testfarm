# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, session,redirect,url_for
from sqlite3 import Error
import json,apiai, requests, datetime, sqlite3
import http.client, urllib.request, urllib.parse, urllib.error
import pandas as pd
import matplotlib.pyplot as plt
import os
import traceback
from azure.common.credentials import ServicePrincipalCredentials
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.compute.models import DiskCreateOption
from msrestazure.azure_exceptions import CloudError
from haikunator import Haikunator
import time
haikunator = Haikunator()


application = Flask(__name__, template_folder="templates",static_url_path="/static")
#application.config['DEBUG'] = True

# Azure Datacenter
LOCATION = 'eastus'

# Resource Group
GROUP_NAME = 'AgentTED-ResourceGroup'

# Network
VNET_NAME = 'AgentTED-VirtualNetwork'
SUBNET_NAME = 'AgentTED-SubNet1'

# VM
VM_NAME = 'VM-WIN-TED-123'

reply = ''
application.secret_key = '12345'
  

@application.route('/', methods=['POST','GET'])
def login():
    error = None
    if request.method == 'POST':
        username_form  = request.form['username']
        password_form  = request.form['password']
        con = create_connection()
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute("SELECT COUNT(USERNAME) FROM LOGIN_CREDENTIALS WHERE USERNAME = ?", (username_form,)) 
        if cur.fetchone()[0]:
            cur.execute("SELECT PASSWORD, EMAIL FROM LOGIN_CREDENTIALS WHERE USERNAME = ?", (username_form,))
            for row in cur.fetchall():
                if password_form == row[0]:
                    session['username'] = request.form['username']
                    session['email'] = row[1]
                    User = session.get('username')
                    #email = session.get('email')
                    return render_template('index.html', username=User)
                else:
                    error = 'Invalid Credentials. Please try again.'
    return render_template('login.html', error=error)

@application.route('/logout', methods=['POST','GET'])
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

#@application.route("/")
#def home():
#    return render_template("index.html")

@application.route("/get")
def get_bot_response():
    username = session.get('username')
    user_email= session.get('email')
    priority_lst = {'low': 1 ,'medium': 2 , 'high':3,  'urgent': 4}
    """ Fetching user dialog from UI """
    userText = request.args.get('msg')

    airequest = Dialogflow_connection() 
    
    airequest.query = userText
    airesponse = airequest.getresponse()
    raw_data = airesponse.read()
	# JSON default
    encoding = airesponse.info().get_content_charset('utf8')  
   
    obj = json.loads(raw_data.decode(encoding))
    
    reply = obj['result']['fulfillment']['speech']
    ticket_type=str(obj['result']['action'])
    action = ticket_type
    azure_subscription='yes'
    print(action)
    print(str(obj['result']['parameters']))
    
    if action=='show':
        
        print("In show ticket")
        ticket_id=str(obj['result']['parameters']['ticketid'])
        display =str(obj['result']['parameters']['display'])
        print(ticket_id)
        print(display)
        
        if (ticket_id != '' and display != ''):
            
            res = show_ticket(ticket_id)
            if res.status_code == 200:
                print ("Request processed successfully, the response is given below")
                priority_map = {1:'low', 2:'medium', 3:'high', 4:'urgent'}
               
                L1 = "please find below the ticket details"
                L2 = " <br /> <b>Ticket Id</b>: " + str(res.json()['id'])
                L3 = " <br /> <b>Requestor Email</b>: " + res.json()['requester']['email']
                L4 = " <br /> <b>Ticket Type</b>: " + res.json()['type']
                L5 = " <br /> <b>Ticket Description</b>: " + res.json()['description_text']
                
                prioroty_disp = priority_map[res.json()['priority']]
                L6 = " <br /> <b>Priority</b>: " + str(prioroty_disp)

                reply = L1 + L2 + L6 + L3 + L4 + L5 

            else:
                    reply = "Failed to fetch ticket details, please check with a valid ticket id"

        obj = ''
            
    

    if action=='update':
        
        print("In update ticket")
        ticket_id=str(obj['result']['parameters']['ticketid'])
        tkt_priority=str(obj['result']['parameters']['priority'][0])
       

        update=str(obj['result']['parameters']['update'])
        
        reply = obj['result']['fulfillment']['speech']

        print(ticket_id)
        
        if (ticket_id != '' and tkt_priority != '' and update != ''):
            
            tkt_priority = priority_lst[tkt_priority.lower()]
            res = update_ticket(ticket_id, tkt_priority)

            if res.status_code != 200:
                reply = "Failed to update ticket, please check with a valid ticket id and priority"

        obj = ''
            
    
    if action=='L0':
        
        """ call to QNA forgetting replies from FAQ pages """
        query = str(obj['result']['resolvedQuery'])
        tkt_priority = 1
        tkt_status = 4
        resp_from_QNA = QNA(query)
        Deflt_resp = "No good match found in the KB"
                
        if resp_from_QNA.lower() == Deflt_resp.lower() :
            resp_from_QNA = "Sorry, I am not trained for this"
        
        """ Establishing connection with Agentted.db """
        con = create_connection()
        cur = con.cursor()
        
        """ Logging ticket for L0 """
        cur.execute("INSERT INTO TICKETS (NAME, CATEGORY,QUERY) VALUES (?,?,?)",(username,ticket_type,query) )
        con.commit()
        
        con.close()
        ticket_id = log_ticket(ticket_type, query, user_email, tkt_priority, tkt_status)
        reply = str(resp_from_QNA)
        obj = ''
        print('L0 ticket lodged')
    
    if action=='L1':
        status = ''
        status_updt = 'RUNNING'
        """  Extracting Entities from return obj of dialogflow """ 
        print(str(obj['result']['parameters']['Vmname']))
        Vmname=str(obj['result']['parameters']['Vmname'])
        action=str(obj['result']['parameters']['action'])
        tkt_priority = 1
        tkt_status = 4
        
        print(Vmname)
        query = action + Vmname
        
        """  Validating if all the required entities for L1 are extracted from user dialogs """ 
        if (Vmname != '' and action != ''):
            
            """  Establishing connection with Agentted.db """ 
            con = create_connection()
            cur = con.cursor()
            
            """ Fetching the status of the """
            select_str = "select VM_STATUS from VM_INSTANCE where VM_NAME = '" + Vmname + "'" 
            print(select_str)
            cur.execute(select_str)
            rows = cur.fetchall()
            print(rows)
            for row in rows:
                print("inside for")
                status = row[0]
                status = status.lower()
                type(status)
                print(status)
                
            action = action.lower()
            
            print(action)
            stop_lst= ['stop' , 'shutdown' , 'shut down']
            start_lst = ['start' , 'run']
            terminate_list = ['terminate']
            
            restart_list = ['restart' , 'reboot']

           
            if (status == ''):
                
                reply = Vmname + ' does not exist.'
                print(reply)
                obj = ''
            
            elif ((action in  start_lst ) and (status == 'running')):   
                
                reply = Vmname + ' is already running.'
                print(reply)
                obj = ''
            
            elif ((action in  stop_lst ) and (status == 'stopped')):
                
                reply = Vmname + ' is already stopped'
                print(reply)
                obj = ''
	        
            elif (((action in  start_lst) or (action in  stop_lst) or (action in  terminate_list) or (action in  restart_list)) and (status == 'terminated')):
                
                reply = Vmname + ' is already terminated. No further operations can be performed.'
                print(reply)
                obj = ''
            else:
#                status_updt = 'RUNNING'
                if (action in  start_lst ) : 
                    if (azure_subscription=='yes'):
                        exit_code=start_vm(Vmname)
                        time.sleep(15)
                        if (exit_code=='Succeeded'):
                            status_updt = 'RUNNING'
                        else:
                            status_updt = 'FAILED TO START'
                    elif (azure_subscription=='no'):
                          status_updt = 'RUNNING'
                        
                               
                if (action in  stop_lst ) :
                    
                    if (azure_subscription=='yes'):
                        exit_code=stop_vm(Vmname)
                        time.sleep(15)
                        if (exit_code=='Succeeded'):
                            status_updt = 'STOPPED'
                        else:
                            status_updt = 'FAILED TO STOP'
                    elif (azure_subscription=='no'):
                          status_updt = 'STOPPED'

                    if (action in  restart_list ) :
                    
                        if (azure_subscription=='yes'):
                        
                            exit_code=restart_vm(Vmname)
                        
                            time.sleep(15)
                        
                        if (exit_code=='Succeeded'):
                            status_updt = 'RESTARTED'
                            
                        else:
                            status_updt = 'FAILED TO RESTART'
                    elif (azure_subscription=='no'):
                        
                          status_updt = 'RESTARTED'
                          
                if (action in  terminate_list ) :
                    
                    status_updt = 'TERMINATED'
                    
                update_str = "update VM_INSTANCE set VM_STATUS = '" + status_updt + "' where  VM_NAME = '" + Vmname + "'"  

                print(update_str)
                cur.execute(update_str)
                con.commit()
                
            
                """  Logging ticket for L1 """ 
                cur.execute("INSERT INTO TICKETS (NAME,CATEGORY,QUERY, VMNAME, ACTION ) VALUES (?,?,?,?,?)",(username,ticket_type, query, Vmname, action) )
                con.commit()
                
                select_str = "SELECT MAX(TICKET_ID) FROM TICKETS"
                cur.execute(select_str)
                rows = cur.fetchall()

                for row in rows:
                    max_id = row[0]
                    print(max_id)
                con.close()
                reply = "Ticket: " + str(max_id) + " " + str(reply)
                ticket_id = log_ticket(ticket_type, query, user_email, tkt_priority, tkt_status)
                reply = Vmname + " is sucessfully " + action + "ed. ticket_id: " + str(ticket_id) 
                obj = ''
                print('L1 ticket lodged')

    if action=='L11':
        
        """  Extracting Entities from return obj of dialogflow """
        ticket_type = 'L1'
        print(str(obj['result']['parameters']['Env']))
        Env=str(obj['result']['parameters']['Env'])
        vmSize=str(obj['result']['parameters']['vmSize'])
        action='provision'
        #print(obj)
        tkt_priority = 1
        tkt_status = 4
        query = 'provision ' + vmSize +" instance in " + Env
        print(query)
        """  Validating if all the required entities for L1 are extracted from user dialogs """ 
        if (Env != '' and action != '' and vmSize != ''):
            
            if (Env.lower() == 'prod' or Env.lower() == 'production'):
            
                reply = 'Sorry. As per policy I can not provision you a new instance in production environment.'
                obj = ''
                print(reply)
            
            else:
                print('in else')
                """  Establishing connection with Agentted.db """ 
                con = create_connection()
                cur = con.cursor()
            
                select_str = "SELECT MAX(TICKET_ID) FROM TICKETS"
                cur.execute(select_str)
                rows = cur.fetchall()
                
                for row in rows:
                    print(row)
                    current_ticketid = row[0]
                
                vm_id = str(int(current_ticketid) + 1).zfill(3)

                vmname = 'vm-win-' + vmSize + '-'+ Env + '-' + vm_id
                ## adding new entry to the entity vmname
                dialogflow_entity(vmname)
                SUBSCRIPTION_ID = 'xxxx-xxxx-xxxx-xxxx' 
                VM_STATUS = 'RUNNING'
                """  Logging ticket for L1 """ 
                cur.execute("INSERT INTO TICKETS (NAME,CATEGORY,QUERY, ACTION, VM_SIZE, ENV, vmname) VALUES (?,?,?,?,?,?,?)",(username, ticket_type, query, action, vmSize, Env, vmname) )
                con.commit()
                time_stamp = str(datetime.datetime.utcnow())
                cur.execute("INSERT INTO VM_INSTANCE (USER_NAME, SUBSCRIPTION_ID , VM_NAME, VM_STATUS, VM_SIZE, ENV, LAUNCH_DATE) VALUES (?,?,?,?,?,?,?)",(username, SUBSCRIPTION_ID, vmname, VM_STATUS, vmSize, Env, time_stamp) )

                con.commit()
            
                select_str = "SELECT MAX(TICKET_ID) FROM TICKETS"
                cur.execute(select_str)
                rows = cur.fetchall()
                
                for row in rows:
                    print(row)
                    ticket_id = row[0]
                
                ticket_id = log_ticket(ticket_type, query, user_email, tkt_priority, tkt_status)
                
                           
                con.close()
                
                L1='Please hold on while the VM is provisioned…. <br /> <br /> Provisioning a ' + vmSize
                L2=' VM with Windows OS (in Subscription, with SubscriptionId : xxxx-xxxx-xxxx-xxxx)… <br /> <br /> Provisioning Successful… Instance ID ' + vmname
                L3=' <br /> <br /> Under ticket: ' + str(ticket_id)
                L4='<br /> <br /> Admin user id & pwd for the newly provisioned VM are sent to your email'
                
                reply = L1+L2+L3+L4
                obj = ''
                print('L11 ticket lodged')
                       
    if action=='L2':
        
        """   Extracting Entities from return obj of dialogflow """ 
        Vmname=str(obj['result']['parameters']['Vmname'])
        user=str(obj['result']['parameters']['user'])
        description=str(obj['result']['parameters']['description'])
        tkt_priority = str(obj['result']['parameters']['priority'])
        
        
        query =  Vmname + ' ' + description
        tkt_status = 2
       
        """  Validating if all the required entities for L2 are extracted from user dialogs """ 
        if (Vmname != '' and user != '' and description != '' and tkt_priority != ''):
           
            """   Establishing connection with Agentted.db """ 
            con = create_connection()
            cur = con.cursor()
            
            """  Logging ticket for L2 """ 
            cur.execute("INSERT INTO TICKETS (NAME, CATEGORY, QUERY, VMNAME, USER, SHORT_DESC) VALUES (?,?,?,?,?,?)",(username, ticket_type, query, Vmname, user, description) )
            con.commit()
            
            """  Fetching the ticket id of the previous logged ticket """ 
            select_str = "SELECT MAX(TICKET_ID) FROM TICKETS"
            cur.execute(select_str)
            rows = cur.fetchall()
            
            for row in rows:
                max_id = row[0]
                print(max_id)
           
            con.close()
            tkt_priority = priority_lst[tkt_priority.lower()]
            ticket_id = log_ticket(ticket_type, query, user_email, tkt_priority, tkt_status)
            reply = "Ticket: " + str(ticket_id) + " " +str(reply)
            obj = ''
            
    return str(reply)
    
    
@application.route('/foo', methods=['POST','GET'])
def tickets():
    con = create_connection()
    print("In function")
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("select * from TICKETS")
    rows = cur.fetchall()
    return render_template("list.html",rows = rows)
        
def main():
    table_creation()
    application.run(debug=True)
    #application.run(host='0.0.0.0', port=5151)

def Dialogflow_connection():
    
    CLIENT_ACCESS_TOKEN = '339d47f35f864a849a6dd17b6e3ede46'
    ai = apiai.ApiAI(CLIENT_ACCESS_TOKEN)
    airequest = ai.text_request()
    airequest.lang = 'de'  # optional, default value equal 'en'
    airequest.session_id = "<SESSION ID, UNIQUE FOR EACH USER>"
    return airequest

def table_creation():
   
    conn = create_connection()
    conn.execute('CREATE TABLE IF NOT EXISTS TICKETS (TICKET_ID INTEGER PRIMARY KEY AUTOINCREMENT, NAME CHAR(100), CATEGORY CHAR(10), QUERY CHAR(100), VMNAME CHAR(100), ACTION CHAR(100), USER CHAR(100), SHORT_DESC CHAR(100), VM_SIZE CHAR(100), ENV CHAR(100))')
    conn.execute('CREATE TABLE IF NOT EXISTS LOGIN_CREDENTIALS (USERNAME CHAR(200), PASSWORD CHAR(100), EMAIL CHAR(10))')
    name = 'dummy'
    query = 'testing'
    tkt_type = 'L0'
    conn.execute("INSERT INTO TICKETS (NAME, QUERY,CATEGORY) VALUES (?,?,?)",(name, query,tkt_type) )
    conn.commit()
    conn.execute("INSERT INTO LOGIN_CREDENTIALS (USERNAME, PASSWORD ,EMAIL) VALUES (?,?,?)",('admin', 'admin','admin@gmail.com') )
    conn.execute("INSERT INTO LOGIN_CREDENTIALS (USERNAME, PASSWORD ,EMAIL) VALUES (?,?,?)",('user1', 'ted@123','user1@gmail.com') )
    conn.execute("INSERT INTO LOGIN_CREDENTIALS (USERNAME, PASSWORD ,EMAIL) VALUES (?,?,?)",('user2', 'ted@123','user2@gmail.com') )
    conn.commit()
    conn.execute('CREATE TABLE IF NOT EXISTS VM_INSTANCE (USER_NAME CHAR(100), SUBSCRIPTION_ID CHAR(100), VM_NAME CHAR(100), VM_STATUS CHAR(100), VM_SIZE CHAR(100) , ENV CHAR(100), LAUNCH_DATE CHAR(100))')

    conn.close()
    print("Tables created")

def create_connection():

    try:
        conn = sqlite3.connect('Agent_Ted2.db')
        return conn
    except Error as e:
        print(e)
    return None

def QNA(qsn):
    headers = {
    # Request headers
        'Content-Type': 'application/json',
        'Ocp-Apim-Subscription-Key': '6b87248960c1422da579715d1ffd818a',
        }
    body = "{'question':'" + qsn + "'}"

    params = urllib.parse.urlencode({
    })

    try:
        conn = http.client.HTTPSConnection('westus.api.cognitive.microsoft.com')
        conn.request("POST", "/qnamaker/v2.0/knowledgebases/45003c99-ffd5-4165-828d-4f427b6b2f56/generateAnswer?%s" % params, body, headers)
        response = conn.getresponse()
        #data = response.read()
        raw_data = response.read()
        type(raw_data)
        encoding = response.info().get_content_charset('utf8')  # JSON default
        obj = json.loads(raw_data.decode(encoding))
        reply = obj["answers"][0]["answer"]
        conn.close()
    except Exception as e:
        print("[Errno {0}] {1}".format(e.errno, e.strerror))
  
    return reply


def dialogflow_entity(vmname):
    url = 'https://api.api.ai/v1/entities/Vmname/entries?v=20150910'
    
    headers = {'Authorization': 'Bearer'+ '66c14b477ef349c7b1d01922224508e2' ,'Content-Type': 'application/json'}
    
    data = " [ { 'value': '" + vmname  + "' } ] "
    response = requests.post(url,headers=headers,data=data)
    print(response)
    print(response.json)
    
def log_ticket(ticket_type, query, user_email, priority, status):
	api_key = "1d3OInmn7R770ovj0ZZI"
	domain = "infosysanudeep"
	password = "x"
	ticket_id = ""


	headers = { 'Content-Type' : 'application/json' }

	ticket = {
		'subject' : ticket_type,
		'description' : query,
		'email' : user_email,
		'type': ticket_type,
		'priority' : priority,
		'status' : status,
        'source' : 7,
	}

	r = requests.post("https://"+ domain +".freshdesk.com/api/v2/tickets", auth = (api_key, password), headers = headers, data = json.dumps(ticket))

	if r.status_code == 201:
	  print ("Ticket created successfully, the response is given below")
	  ticket_id = r.json()['id']
	  print ("Location Header : " + r.headers['Location'])
	  return ticket_id
	else:
	  print ("Failed to create ticket, errors are displayed below,")
	  response = r.json()
	  print (response["errors"])

	  print ("x-request-id : " + r.headers['x-request-id'])
	  print ("Status Code : " + str(r.status_code))
	  return ticket_id

def show_ticket(ticket_id):
    api_key = "1d3OInmn7R770ovj0ZZI"
    domain = "infosysanudeep"
    password = "x"

	# Id of the ticket to be updated
	#ticket_id = '12'
    res = requests.get("https://"+ domain +".freshdesk.com/api/v2/tickets/"+ ticket_id +"?include=requester", auth = (api_key, password))
    return res

def update_ticket(ticket_id,priority):
	api_key = "1d3OInmn7R770ovj0ZZI"
	domain = "infosysanudeep"
	password = "x"

	headers = { 'Content-Type' : 'application/json' }

	ticket = {
	  'priority' : int(priority),
	}

	res = requests.put("https://"+ domain +".freshdesk.com/api/v2/tickets/"+ticket_id, auth = (api_key, password), headers = headers, data = json.dumps(ticket))
	return res


@application.route('/dashboard', methods=['POST','GET'])
def dashboard():
      con = create_connection()
      con.row_factory = sqlite3.Row
      cur = con.cursor()
      username = session.get('username')
      cur.execute("select * from VM_INSTANCE WHERE USER_NAME=?",(username,))
      rows = cur.fetchall()
      print(rows)
      dataframe = pd.read_sql_query("select * from TICKETS", con)

      print(dataframe['CATEGORY'])
      print(dataframe['CATEGORY'].value_counts())

      fig = plt.figure()    
      dataframe.groupby('CATEGORY').size().plot(kind='bar')
      path='static/media/graph.png'

      print(path)
      fig.savefig(path)

      print("path ",path)
      return render_template("dashboard.html",path=path,rows=rows)
  
#def dashboard():
#      con = create_connection()
#      dataframe = pd.read_sql_query("select * from TICKETS", con)
##      print(dataframe)
##      print(dataframe['CATEGORY'])
##      print(dataframe['CATEGORY'].value_counts())
#
#      fig = plt.figure()    
#      dataframe.groupby('CATEGORY').size().plot(kind='bar')
#      path='static/media/graph.png'
#   
#      fig.savefig(path)
#
#      print("path ",path)
#      return render_template("dashboard.html",path=path)
#          

def get_credentials():
   
    subscription_id = "1e9db46c-8d0b-48b9-af0d-568bfe41f139"
    credentials = ServicePrincipalCredentials(
        client_id = "1ba3737e-b8f9-4ad4-9770-51fdb0ce5637",
        secret = "1zHH/NzNybuzfk6K1yR4IdEjZUo/rrw3MeNR1nfxYmk=",
        tenant = "73ffdfaa-cac5-4972-9af1-573cfbf91a00"
    
    )
    return credentials, subscription_id


def start_vm(VM_NAME):

    credentials, subscription_id = get_credentials()
#    resource_client = ResourceManagementClient(credentials, subscription_id)
    compute_client = ComputeManagementClient(credentials, subscription_id)
#    network_client = NetworkManagementClient(credentials, subscription_id)
      
    # Get the virtual machine by name
    print('\nGet Virtual Machine by Name')
    virtual_machine = compute_client.virtual_machines.get(
        GROUP_NAME,
        VM_NAME
    )
     
    # Start the VM
    print('\nStart VM')
    async_vm_start = compute_client.virtual_machines.start(GROUP_NAME, VM_NAME)
    async_vm_start.wait()
    return async_vm_start.status()


def restart_vm(VM_NAME):

    credentials, subscription_id = get_credentials()
#    resource_client = ResourceManagementClient(credentials, subscription_id)
    compute_client = ComputeManagementClient(credentials, subscription_id)
#    network_client = NetworkManagementClient(credentials, subscription_id)


    print('\nGet Virtual Machine by Name')
    virtual_machine = compute_client.virtual_machines.get(
        GROUP_NAME,
        VM_NAME
    )
    
    # Restart the VM
    print('\nRestart VM')
    async_vm_restart = compute_client.virtual_machines.restart(GROUP_NAME, VM_NAME)
    async_vm_restart.wait()
    return async_vm_restart.status()


def stop_vm(VM_NAME):

    credentials, subscription_id = get_credentials()
#    resource_client = ResourceManagementClient(credentials, subscription_id)
    compute_client = ComputeManagementClient(credentials, subscription_id)
#    network_client = NetworkManagementClient(credentials, subscription_id)

    print('\nGet Virtual Machine by Name')
    virtual_machine = compute_client.virtual_machines.get(
        GROUP_NAME,
        VM_NAME
    )

    # Stop the VM
    print('\nStop VM')
    async_vm_stop = compute_client.virtual_machines.power_off(GROUP_NAME, VM_NAME)
    async_vm_stop.wait()
    return async_vm_stop.status()


def list_vm():

    credentials, subscription_id = get_credentials()
    resource_client = ResourceManagementClient(credentials, subscription_id)
    compute_client = ComputeManagementClient(credentials, subscription_id)
#    network_client = NetworkManagementClient(credentials, subscription_id)

    # List VM in resource group
    print('\nList VMs in resource group')
    for vm in compute_client.virtual_machines.list(GROUP_NAME):
        print("\tVM: {}".format(vm.name))

      


if __name__ == "__main__":
    main()

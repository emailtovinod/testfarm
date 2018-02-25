rows = [('running',)]
type(rows)    
for row in rows:
    print(row)
    status = row[0]
    print(status.lower())



import sqlite3
from sqlite3 import Error

def create_connection():

    try:
        conn = sqlite3.connect('Agent_Ted2.db')
        return conn
    except Error as e:
        print(e)
    return None
    
    
con = create_connection()
cur = con.cursor()
Vmname = 'vm-win-large-test-021'

select_str = "select VM_STATUS from VM_INSTANCE where VM_NAME = '" + Vmname + "'" 

status_updt = ''
update_str = "update VM_INSTANCE set VM_STATUS = '" + status_updt + "' where  VM_NAME = '" + Vmname + "'"  

print(update_str)
cur.execute(update_str)
con.commit()

cur.execute(select_str)
status = cur.fetchall()[0][0]
status
print(status)
type(status) 

if status == '' : 
    print ("true" )      

stop_lst= ['stop', 'terminate' , 'shutdown' , 'sut down']   
start_lst = ['start', 'run']

action = 'start'

action in stop_lst

if (action  and status == 'stopped'):
                
    reply = Vmname + ' is already in stopped'
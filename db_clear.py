import sqlite3
#1.连接到数据库
connection = sqlite3.connect('/tmp/mxcube-user.db')
#2.创建游标
cursor = connection.cursor()
#3.执行清空表的SQL命令
cursor.execute("DELETE FROM User")
#4.提交变化
connection.commit()
#5.关闭游标和数据库连接cursor.close（)#关闭游标
connection.close()
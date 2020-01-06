#! usr/bin/python

from flask import Blueprint, request, jsonify, Response, g
from instance import config
import pymysql
import json
import datetime
from utils.dbutils import redis
from utils.token_utils import TokenMaker
from utils.json_helper import DateEncoder
from utils.dbutils import mysqlpool
import cx_Oracle
import uuid
from math import ceil

# 创建数据采集的蓝图
collect_data = Blueprint("collect_data", __name__)

@collect_data.route("/show_worksheet/", methods=["POST"])
def show_wsheet():
    """返回列表和默认分组"""
    uid = g.token.get("id")
    try:
        conn = mysqlpool.get_conn()
        with conn.swich_db("%s_db" % uid) as cursor:
            group_list = []
            if conn.query_all("select * from {}".format(config.ME2_TABLENAME1)):
                all_data = conn.query_all("select * from {}".format(config.ME2_TABLENAME1))
                for i in all_data:
                    data_info = {
                        "id": i["groupid"],
                        "type_name": i["type_name"],
                        "path": i["path"] + "/" + str(i["groupid"])
                    }
                    group_list.append(data_info)
        return jsonify({
            "code": 1,
            "data": group_list
        })

    except Exception as e:
        raise e


@collect_data.route("/save_groups/", methods=["POST"])
def save_group():
    """添加列表分组"""
    uid = g.token.get("id")
    json_data = request.get_json()
    group_name = json_data.get("data")
    group_path = json_data.get("path")
    try:
        conn = mysqlpool.get_conn()
        with conn.swich_db("%s_db"%uid) as cursor:
            conn.insert_one("insert into {TABLE_NAME}(type_name, path) values(%s,%s)".format(
                TABLE_NAME=config.ME2_TABLENAME1), [group_name, group_path])

        return jsonify({
            "code": 1,
            "data": "添加分组成功"
        })
    except Exception as e:
        return jsonify({
            "code": -1,
            "data": "添加失败"
        })


@collect_data.route("/del_groups/", methods=["POST"])
def del_group():
    """删除分组"""
    uid = g.token.get("id")
    json_data = request.get_json()
    group_id = json_data.get("id")
    try:
        conn = mysqlpool.get_conn()
        with conn.swich_db("%s_db"%uid) as cursor:
            conn.delete(" DELETE from worksheet_classification where groupid={ID}".format(ID=group_id))
        return jsonify({
            "code": 1,
            "data": "删除分组成功"
        })
    except Exception as e:
        return jsonify({
            "code": -1,
            "data": "删除失败"
        })


@collect_data.route("/update_groups/", methods=["POST"])
def update_groups():
    """修改分组名"""
    uid = g.token.get("id")
    json_data = request.get_json()
    group_id = json_data.get("id")
    group_name = json_data.get("data")
    conn = mysqlpool.get_conn()
    with conn.swich_db("%s_db"%uid) as cursor:
        conn.update("UPDATE {TABLE} set type_name='{new_table}' where groupid={ID}".format(
            TABLE=config.ME2_TABLENAME1, new_table=group_name, ID=group_id))
    return jsonify({
        "code": 1,
        "data": "修改成功"
    })


@collect_data.route("/show_table_name/", methods=["POST"])
def show_table_name():
    """显示分组表的每张表"""
    json_data = request.get_json()
    # table_id = json_data.get("id")
    type_id = json_data.get("type_id")
    uid = g.token.get("id")
    if type_id != None:
        conn = mysqlpool.get_conn()
        with conn.swich_db("%s_db"%uid, cursor=pymysql.cursors.Cursor) as cursor:
            all_db = conn.query_all(
                "SELECT a.id, a.worksheet_name,a.worksheet_name_cn,a.origin_type_id,b.data_origin_type from {TABLE_NAME1}  a left join {TABLE_NAME2}  b on a.origin_type_id = b.id".format(
                    TABLE_NAME1=config.ME2_TABLENAME2, TABLE_NAME2=config.ME2_TABLENAME3))
            group_name = conn.query_one('select type_name from {} where groupid ={}'.format(config.ME2_TABLENAME1,type_id))
            if not all_db:
                return Response(json.dumps({"code": 1, "data": {"msg": [], "group_name": group_name,
                                                                "num_of_worksheet": 0,
                                                                "group_id": type_id}}),
                                mimetype='application/json')
        table_list = []
        for i in all_db:
            data_info = {
                "id": i[0],
                "table_name": i[1],
                "table_name_cn": i[2],
                "type_id": i[3],
                "type": i[4]
            }
            table_list.append(data_info)
        num_of_worksheet = len(table_list)
        return jsonify({"code": 1, "data": {"msg": table_list, "group_name": group_name,
                                            "num_of_worksheet": num_of_worksheet, "group_id": type_id}})
    else:
        return jsonify({'code': -1, "data": "类型为空"})



@collect_data.route("/connect_db/", methods=['POST'])
def connect_db():
    """连接新的数据库"""
    obj = request.get_json()
    token = obj.get("token")
    sourceid = obj.get("id")
    uid = g.token.get("id")

    if sourceid != None and sourceid != "":

        conn = mysqlpool.get_conn()
        with conn.swich_db(config.WOWRKSHEET01, cursor=pymysql.cursors.Cursor) as cursor:
            data = conn.query_one(
                'select sourceName,sourceType,link,account,password,remark from {TB} where uid={UID} and flag=1 and id="{ID}"'.format(
                    TB=config.TABLENAME4, ID=sourceid, UID=uid))

        if data:
            data = dict(zip(["sourceName", "dataBaseType", "address", "userName", "password", "remark"], data))
        else:
            return jsonify({"code": -1, "data": None})
        method = 3
    else:
        data = obj.get("formDataBase")
        method = obj.get("type")
    redis.hmset(token, data)
    redis.expire(token, 1800)
    pre_link = data.get("address")
    host, pad = pre_link.split(":")
    port, databasename = pad.split("/")
    user = data.get("userName")
    password = data.get("password")
    source_name = data.get("sourceName")
    remark = data.get("remark")
    dbtype = data.get("dataBaseType")
    rentun_msg = {}
    if dbtype.lower() == "mysql":
        try:
            con = pymysql.connect(
                host="{}".format(host),
                user="{}".format(user),
                password="{}".format(password),
                port=int(port),
                db=databasename
            )
        except Exception as e:
            conn_status = {"code": -1, "data": "连接失败"}
            return jsonify(conn_status)
        else:
            conn_status = {"code": 1, "data": "连接成功"}
            mycur = con.cursor()

            if method == 1:
                con.close()
                mycur.close()
                return jsonify(conn_status)
            elif method == 2:
                mark = str(uuid.uuid1())
                conn = mysqlpool.get_conn()
                with conn.swich_db(config.WOWRKSHEET01) as cursor:
                    conn.insert_one(
                        "insert into {}(id,sourceName,sourceType,link,account,password,remark,createDate,uid) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)".format(
                            config.TABLENAME4),
                        [mark, source_name, dbtype, pre_link, user, password, remark,
                         datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), uid])
                rentun_msg.update({"msg": "保存成功"})
            mycur.execute("show tables")
            all_table = mycur.fetchall()
            table_list = [i[0] for i in all_table]
            rentun_msg.update({"code": 1, "data": table_list})
            mycur.close()
            con.close()
            return jsonify(rentun_msg)
    elif dbtype.lower() == "oracle":
        try:
            dsn = cx_Oracle.makedsn(host, port, databasename.upper())
            con = cx_Oracle.connect(user=user, password=password, dsn=dsn, encoding="UTF-8")
        except Exception as e:
            conn_status = {"code": -1, "data": "连接失败"}
            return jsonify(conn_status)
        else:
            conn_status = {"code": 1, "data": "连接成功"}
            mycur = con.cursor()
            if method == 1:
                con.close()
                mycur.close()
                return jsonify(conn_status)
            elif method == 2:
                mark = str(uuid.uuid1())
                conn = mysqlpool.get_conn()
                with conn.swich_db(config.WOWRKSHEET01) as cursor:
                    conn.insert_one(
                        "insert into {}(id,sourceName,sourceType,link,account,password,remark,createDate,uid) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)".format(
                            config.TABLENAME4),
                        [mark, source_name, dbtype, pre_link, user, password, remark,
                         datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), uid])
                rentun_msg.update({"msg": "保存成功"})
            mycur.execute("select OWNER,TABLE_NAME from all_tables")
            all_table = mycur.fetchall()
            table_list = ["%s.%s" % (i[0], i[1]) for i in all_table]
            rentun_msg.update({"code": 1, "data": table_list})
            mycur.close()
            con.close()
            return jsonify(rentun_msg)

@collect_data.route("/return_table_msg/", methods=['POST'])
def return_table_msg():
    """
    返回预备数据
    :return:
    """
    obj = request.get_json()
    table_name = obj.get("table_name")
    token = obj["token"]
    customize_sql = obj.get("customize_sql")
    page = int(obj.get("page")) - 1
    page_size = int(obj.get("page_size"))
    dbmsg = redis.hgetall(token)
    if not dbmsg:
        return jsonify({"code": -1, "data": "请求超时"})
    dbmsg['table_name'] = table_name

    redis.hmset(token, dbmsg)
    redis.expire(token, 1800)

    uid = g.token.get("id")
    pre_link = dbmsg["address"]
    host, pad = pre_link.split(":")
    port, databasename = pad.split("/")
    user = dbmsg["userName"]
    password = dbmsg["password"]
    dbtype = dbmsg["dataBaseType"]
    if dbtype.lower() == "mysql":
        db = pymysql.connect(
            host="{}".format(host),
            user="{}".format(user),
            port=int(port),
            password="{}".format(password),
            db=databasename
        )

        cur = db.cursor(cursor=pymysql.cursors.DictCursor)
        cur.execute("select count(*) from %s" % table_name)
        whole_page = ceil(list(cur.fetchone().values())[0] / page_size)
        sql = "select * from %s limit %s,%s;" % (table_name, page * page_size, page_size)

        if customize_sql:
            if customize_sql.lower().startswith("select"):
                sql = customize_sql
                sql_split = customize_sql.split(" ")
                table_name = sql_split[sql_split.index("from") + 1]
            else:
                return jsonify({"code": -1, "data": "查询失败"})
        try:
            cur.execute(sql)
        except Exception as e:
            cur.close()
            db.close()
            return jsonify({"code": -1, "data": "查询失败"})
        else:
            fetdata = cur.fetchall()
            cur.execute('show columns from %s;' % table_name)
            pre_data = cur.fetchall()

            field_type = dict(zip([list(i.values())[0] for i in pre_data], [list(i.values())[1] for i in pre_data]))
            cur.close()
            db.close()
            return Response(json.dumps({"code": 1, "data": fetdata, "field_type": field_type, "whole_page": whole_page},
                                       cls=DateEncoder), mimetype='application/json')

    elif dbtype.lower() == "oracle":
        from utils.dbutils import makeDictFactory
        dsn = cx_Oracle.makedsn(host, port, databasename.upper())
        conn = cx_Oracle.connect(user=user, password=password, dsn=dsn, encoding="UTF-8")

        cur = conn.cursor()
        cur.execute("select count(*) from %s" % table_name.upper())
        whole_page = ceil(cur.fetchone()[0] / page_size)
        sql = "select * from {TABLE} where rowid in (select rid from (select rownum rn,rid from (select rowid rid from {TABLE}) where rownum < {UL}) where rn > {LL})".format(
            TABLE=table_name.upper(), UL=page_size + page * page_size, LL=page * page_size)
        if customize_sql:
            if customize_sql.lower().startswith("select"):
                sql = customize_sql
                sql_split = customize_sql.split(" ")
                table_name = sql_split[sql_split.index("from") + 1].replace(".", "_")
            else:
                return jsonify({"code": -1, "data": "查询失败"})
        try:
            cur.execute(sql)
            cur.rowfactory = makeDictFactory(cur)
        except Exception as e:
            cur.close()
            conn.close()
            return jsonify({"code": -1, "data": "查询失败"})
        else:
            fetdata = cur.fetchall()
            t_o_l = table_name.split('.')
            cur.execute(
                "select column_name,data_type from all_tab_columns WHERE TABLE_NAME = '%s' and OWNER = '%s'" % (
                    t_o_l[1].upper(), t_o_l[0]).upper())
            pre_data = cur.fetchall()
            field_type = dict(zip([i[0] for i in pre_data], [i[1] for i in pre_data]))
            cur.close()
            conn.close()
            return Response(json.dumps({"code": 1, "data": fetdata, "field_type": field_type, "whole_page": whole_page},
                                       cls=DateEncoder),
                            mimetype='application/json')

@collect_data.route("/save_table/", methods=['POST'])
def save_table():
    """
    保存工作表
    :return:
    """
    uid = g.token.get("id")
    obj = request.get_json()
    token = obj["token"]
    table_type = obj["tableType"]
    change_table_datas = obj["changeTableDatas"]

    cash_msg = redis.hgetall(token)
    pre_link = cash_msg["address"]
    host, pad = pre_link.split(":")
    port, databasename = pad.split("/")
    user = cash_msg["userName"]
    password = cash_msg["password"]
    dbtype = cash_msg["dataBaseType"]
    table_name = cash_msg['table_name']  # 表名

    # 获取数据库连接cur和创建表语句create_table_msg
    if dbtype.lower() == "mysql":
        db = pymysql.connect(
            host="{}".format(host),
            user="{}".format(user),
            port=int(port),
            password="{}".format(password),
            db=databasename
        )

        cur = db.cursor(cursor=pymysql.cursors.DictCursor)
        cur.execute("show create table %s;" % table_name)
        create_table_msg = cur.fetchall()[0]
        cur.execute("show columns from %s;" % table_name)
        columns = [list(i.values())[0] for i in cur.fetchall()]

        sql = "select * from %s" % (table_name)
        res_num = cur.execute(sql)
        dbmsg = cur.fetchmany(config.DATA_PRETREATMENT_SIZE)

    elif dbtype.lower() == "oracle":
        from utils.dbutils import makeDictFactory
        dsn = cx_Oracle.makedsn(host, port, databasename)
        conn = cx_Oracle.connect(user=user, password=password, dsn=dsn, encoding="UTF-8")

        cur = conn.cursor()
        t_o_l = table_name.split('.')
        cur.execute(
            "select column_name from all_tab_columns WHERE TABLE_NAME = '%s' and OWNER = '%s'" % (
                t_o_l[1], t_o_l[0]))

        fetdata = cur.fetchall()
        columns = [i[0] for i in fetdata]

        my_table_name = table_name.replace('.', '_')

        create_table_msg = {'Table': my_table_name}
        create_table_msg['Create Table'] = 'CREATE TABLE `%s`(' % my_table_name

        for i in columns:
            create_table_msg['Create Table'] += '`%s` varchar(255),' % i
        create_table_msg['Create Table'] += ') ENGINE=InnoDB DEFAULT CHARSET=utf8 ROW_FORMAT=COMPACT'

        sql = "select * from %s" % table_name
        res_num = cur.execute(sql)
        cur.rowfactory = makeDictFactory(cur)
        dbmsg = cur.fetchmany(config.DATA_PRETREATMENT_SIZE)

    conn = mysqlpool.get_conn()
    with conn.swich_db("%s_db" % uid) as cursor:
        for ctd in change_table_datas:
            try:
                tb_name = ctd["tableName"] if ctd["tableName"] else create_table_msg["Table"]
            except Exception as e:
                return jsonify({"code": -1, "data": "操作超时"})
            if conn.query_one('select * from {} where worksheet_name = %s'.format(config.ME2_TABLENAME2),
                              tb_name):
                return jsonify({"code": -1, "data": "%s表已存在" % tb_name})
            else:
                conn.drop('drop table if EXISTS %s' % tb_name)
                conn.drop('drop table if EXISTS %s' % (tb_name + "_cn"))
                conn.commit()
                try:
                    conn.insert_one(
                        'insert into {}(worksheet_name,types,worksheet_name_cn,groupid,origin_type_id) values(%s,%s,%s,%s,%s)'.format(
                            config.ME2_TABLENAME2),
                        [tb_name, dbtype, ctd["chineseTableName"], ctd["groupName"], table_type])
                except Exception as e:
                    return jsonify({"code": -1, "data": "插入关键数据失败"})
                try:
                    conn.create(
                        'create table ' + tb_name + '_cn' + ' (id int primary key auto_increment,prime_name varchar(128),cn_name varchar(128),status int default 1)')
                except Exception as e:
                    return jsonify({"code": -1, "data": "创建失败"})
                try:
                    conn.insert_many(
                        'insert into ' + tb_name + '_cn' + '(prime_name,cn_name,status) values(%s,%s,%s)',
                        [(i["englishName"], i["chineseName"], i["code"]) for i in ctd["tableField"]])
                except Exception as e:
                    return jsonify({"code": -1, "data": "插入数据失败"})
                try:
                    conn.create(create_table_msg["Create Table"])
                    baifens = '%s'
                    for j in range(len(columns) - 1):
                        baifens += ',%s'
                    conn.insert_many('insert into ' + tb_name + ' values(' + baifens + ')',
                                    [tuple(i.values()) for i in dbmsg])
                except Exception as e:
                    return jsonify({"code": -1, "data": "操作失败"})
                #if res_num > config.DATA_PRETREATMENT_SIZE:
                    #rdb_migrade.apply_async((cash_msg, uid, tb_name, baifens))  # 异步任务

    return jsonify({"code": 1, "data": "操作成功"})

@collect_data.route("/worksheet_entity/", methods=['POST'])
def worksheet_entity():
    """
    返回工作表内容
    :return:
    """
    uid = g.token.get("id")
    obj = request.get_json()
    worksheet_name = obj["tableName"]
    conn = mysqlpool.get_conn()
    with conn.swich_db("%s_db"%uid) as cursor:
        try:
            worksheet_entity = conn.query_all("select * from %s" % worksheet_name)
        except Exception as e:
            return jsonify({"code": -1, "data": "操作失败"})
        try:
            predata = conn.query_one(
                "select worksheet_name_cn from {} where worksheet_name = %s".format(config.ME2_TABLENAME2),
                worksheet_name)
            sheet_cn = list(predata.values())[0]
        except Exception as e:
            return jsonify({"code": -1, "data": "操作失败"})
        try:
            table_cn = worksheet_name + '_cn'
            field_status = conn.query_all('select prime_name,cn_name,status from %s' % table_cn)
        except Exception as e:
            field_status = None
        try:
            pre_data = conn.query_all('show columns from %s;' % worksheet_name)
            field_type = dict(zip([list(i.values())[0] for i in pre_data], [list(i.values())[1] for i in pre_data]))
        except Exception as e:
            field_type = None

    return jsonify(
        {"code": 1, "data": worksheet_entity, 'worksheet_name_cn': sheet_cn, 'field_status': field_status,
         'field_type': field_type})


@collect_data.route("/drop_worksheet/", methods=['POST'])
def drop_worksheet():
    """删除工作表"""
    obj = request.get_json()
    drop_list = obj['drop_list']
    fm = '%s'
    for i in range(len(drop_list) - 1):
        fm += ',%s'
    conn = mysqlpool.get_conn()
    uid = g.token.get("id")
    with conn.swich_db("%s_db"%uid, cursor=pymysql.cursors.Cursor) as cursor:
        try:
            decide = conn.query_all(
                'select worksheet_name from {} where id in ('.format(config.ME2_TABLENAME2) + fm + ')', drop_list)
            if decide:
                worksheet_names = [i[0] for i in decide]
                worksheet_name_cns = [i + '_cn' for i in worksheet_names]
                fmm = '`%s`'
                for i in range(len(worksheet_names) - 1):
                    fmm += ",'%s'"
                for j in tuple(worksheet_names):
                    conn.drop("drop table if EXISTS `{}`".format(j))
                for jj in tuple(worksheet_name_cns):
                    conn.drop("drop table if EXISTS `{}`".format(jj))

                for wn in worksheet_names:
                    conn.delete("delete from {TABLE_NAME} where worksheet_name = %s".format(
                        TABLE_NAME=config.ME2_TABLENAME2), wn)
            else:
                return jsonify({"code": -1, "data": "不存在该工作表"})
        except Exception as e:
            return jsonify({"code": -1, "data": "操作失败"})
        else:
            return jsonify({"code": 1, "data": "操作成功"})


@collect_data.route("/search_tablename/", methods=["POST"])
def search_tablename():
    """表名模糊查询"""
    conn = mysqlpool.get_conn()
    uid = g.token.get("id")
    try:
        with conn.swich_db("%s_db" % uid, cursor=pymysql.cursors.Cursor) as cursor:
            json_data = request.get_json()
            group_id = json_data["group_id"]
            type_id = json_data["type_id"]
            like_tablename = json_data["like_tablename"]
            if type_id == 0:
                all_db = conn.query_all(
                    "SELECT w.id, w.worksheet_name, w.worksheet_name_cn, w.origin_type_id, o.data_origin_type FROM {TABLE_NAME1} as w LEFT JOIN {TABLE_NAME2} as o on w.origin_type_id = o.id  where w.groupid={group_id} and ( w.worksheet_name_cn LIKE '%{like_tablename}%');".format(
                        TABLE_NAME1=config.ME2_TABLENAME2, TABLE_NAME2=config.ME2_TABLENAME3, group_id=group_id,
                        type_id=type_id, like_tablename=like_tablename))
            else:
                all_db = conn.query_all(
                    "SELECT a.id, a.worksheet_name, a.worksheet_name_cn, a.origin_type_id, b.data_origin_type FROM {TABLE_NAME1} as a LEFT JOIN {TABLE_NAME2} as b on a.origin_type_id = b.id  where a.groupid={group_id} and a.origin_type_id={type_id} and ( a.worksheet_name_cn LIKE '%{like_tablename}%');".format(
                        TABLE_NAME1=config.ME2_TABLENAME2,
                        TABLE_NAME2=config.ME2_TABLENAME3, group_id=group_id, type_id=type_id,
                        like_tablename=like_tablename))

            table_list = []
            if not all_db:
                return jsonify({
                    "code": 1,
                    "data": "搜索不到相关数据"
                })
            for i in all_db:
                data_info = {
                    "id": i[0],
                    "table_name": i[1],
                    "table_name_cn": i[2],
                    "type_id": i[3],
                    "type": i[4]
                }
                table_list.append(data_info)
            group_name = conn.query_one("SELECT type_name FROM {TABLE_NAME3} where groupid={group_id};".format(
                TABLE_NAME3=config.ME2_TABLENAME1, group_id=group_id))

            if len(table_list) == 0:
                table_list.append('查无此表')
                table_list = table_list[0]
                num_of_worksheet = 0
            else:
                num_of_worksheet = len(table_list)
            return Response(json.dumps({"code": 1, "data": {"msg": table_list, "group_name": group_name,
                                                            "num_of_worksheet": num_of_worksheet,
                                                            "group_id": group_id}}), mimetype='application/json')
    except Exception as e:
       raise e


@collect_data.route("/group_change/", methods=["POST"])
def group_change():
    """更改工作表分组"""
    uid = g.token.get("id")
    json_data = request.get_json()
    group_id = json_data.get("id")
    new_id = json_data.get("new_id")
    worksheet_name = json_data.get("worksheet_name")
    conn = mysqlpool.get_conn()
    with conn.swich_db("%s_db"%uid, cursor=pymysql.cursors.Cursor) as cursor:
        groupid_list = [i[0] for i in conn.query_all('select groupid from %s' % config.ME2_TABLENAME1)]
        if group_id and new_id and worksheet_name and int(new_id) in groupid_list:
            conn.update(
                'update {} set groupid = %s where groupid = %s and worksheet_name = %s'.format(config.ME2_TABLENAME2),
                (new_id, group_id, worksheet_name))
            return jsonify({"code": 1, "data": "更改成功"})

@collect_data.route("/return_dbsource_msg/", methods=['POST'])
def return_dbsource_msg():
    """
    保存的数据库资源
    :return:
    """
    conn = mysqlpool.get_conn()
    with conn.swich_db(config.DBNAME1) as cursor:
        data = conn.query_all("select id,sourceName,sourceType from {} where uid=%s".format(config.TABLENAME4),
                              g.token.get("id"))
    return jsonify({"code": 1, "data": data})








from tasks.celery import celery
from tasks.tasks_general import add
@collect_data.route("/testtask/", methods=['POST'])
def testtask():
    res = add.apply_async((3,7),countdown=120,queue='schedule_tasks',routing_key='schedule_tasks')
    return jsonify({'code':1,'id':res.task_id})


from utils.celery_sqlalchemy_scheduler.models import PeriodicTask, IntervalSchedule
from tasks.celery import beat_session

@collect_data.route("/taskschedule/", methods=['POST'])
def taskschedule():
    token = g.token.get('token')
    schedule = IntervalSchedule(every=20, period=IntervalSchedule.SECONDS)
    task_id = TokenMaker().generate_token(token,datetime.datetime.now())
    task = PeriodicTask(id=task_id,interval=schedule,name='my_task',task='tasks.tasks_general.add',args=json.dumps([16,16]))
    beat_session.add(task)
    beat_session.commit()
    return jsonify({'code':1,'id':task_id,'model':'PeriodicTask'})

from tasks.celery import CeleryResult
@collect_data.route("/queryresult/", methods=['POST'])
def queryresult():  
    json_data = request.get_json()
    task_id = json_data.get('task_id')
    state = CeleryResult(task_id).state
    return jsonify({'code':1,'state':state})

@collect_data.route("/tasksrevoke/", methods=['POST'])
def tasksrevoke():  
    json_data = request.get_json()
    task_id = json_data.get('task_id')
    celery.control.terminate(task_id,signal='SIGKILL')

    return jsonify({'code':1})

import importlib
@collect_data.route("/intervaltasksrevoke/", methods=['POST'])
def intervaltasksrevoke():  
    json_data = request.get_json()
    task_id = json_data.get('task_id')
    model = json_data.get('model')
    beat_model = importlib.import_module('utils.celery_sqlalchemy_scheduler.models').__getattribute__(str(model))
    beat_row = beat_session.query(beat_model).filter(beat_model.id==task_id).first()
    beat_row.enabled = 0
    beat_session.commit()
    return jsonify({'code':1})
# !/usr/bin/python3
# -*-coding:utf-8-*-
# Author: len chen
# CreateDate: 2021/10/22 10:04 下午
# Description:
import json
import random
from db_models.models import Service
from utils.prometheus.target_service_mysql import ServiceMysqlCrawl


def target_service_run(env, services):
    """
    组建巡检
    :env: 环境 queryset 对象
    :services: 组件服务id 列表
    """
    # 查询该环境下服务
    services = Service.objects.filter(env=env, service__in=services)
    services = services.values('service_instance_name', 'ip',
                               'service_port', 'service__app_name',
                               'service__app_install_args',
                               'service__app_controllers', 'service_status')
    tmp_list = list()
    tag_total_num = tag_error_num = 0  # 总指标数、异常指标数
    for i in services:
        tmp = {}
        # 组装端口
        service_port = ''
        service_ports = []
        ports = json.loads(i.get('service_port'))\
            if i.get('service_port') else []
        for p in ports:
            service_ports.append(p.get('port'))
            if p.get('key') == 'service_port':
                service_port = p.get('port')
        # 组装服务状态
        serv_status = {0: "正常", 1: "启动中", 2: "停止中", 3: "重启中", 4: "停止"}
        service_status = serv_status.get(i.get('service_status'))
        if i.get('service__app_name') == 'mysql':
            _ = ServiceMysqlCrawl(env=env.name, instance=i.get('ip'))
            _.run()
            # 总指标数/异常指标数 计算
            tag_total_num += 19
            tag_error_num += _.tag_error_num
            tmp.update({
                'id': random.randint(1, 99999999),
                'host_ip': i.get('ip'),
                'cluster_name': "",
                "cpu_usage": _.ret.get('_s').get('cpu_usage'),
                "log_level": "-",
                "mem_usage": _.ret.get('_s').get('mem_usage'),
                "run_time": f"{_.ret.get('run_time')}%",
                "service_name": i.get('service_instance_name'),
                "service_port": service_port,
                "service_status": service_status,
                "service_type": "2",
                "basic": [
                    {"name": "max_memory", "name_cn": "最大内存", "value": ''},
                    {"name": "port_status", "name_cn": "监听端口",
                     "value": service_ports},
                    {"name": "IP", "name_cn": "IP地址", "value": i.get('ip')},
                    {"name": "process_threads", "name_cn": "线程数量",
                     "value": ''},
                    {"name": "conn_num", "name_cn": "连接数量",
                     "value": _.ret.get('threads_connected')},
                    {"name": "aborted_clients", "name_cn": "中断连接数",
                     "value": ""},
                    {"name": "failure_connect", "name_cn": "失败连接数",
                     "value": ""},
                    {"name": "slow_query", "name_cn": "慢查询",
                     "value": _.ret.get('slow_queries')},
                    {"name": "backup_status", "name_cn": "数据同步状态",
                     "value": _.ret.get("slave_sql_running")}
                ]
            })
        elif i.get('service_instance_name') == 'jdk':
            tag_total_num += 11     # 总指标数/异常指标数 计算
            tmp.update({
                'id': random.randint(1, 99999999),
                'host_ip': '-',
                'cluster_name': "-",
                "cpu_usage": "-",
                "log_level": "-",
                "mem_usage": "-",
                "run_time": "-",
                "service_name": i.get('service_instance_name'),
                "service_port": '-',
                "service_status": service_status,
                "service_type": "2",
                "basic": [
                    {"name": "app_install_args", "name_cn": "安装参数",
                     "value": i.get('service__app_install_args')},
                    {"name": "app_controllers", "name_cn": "应用控制脚本",
                     "value": i.get('service__app_controllers')},
                ]
            })
        else:
            tag_total_num += 11     # 总指标数/异常指标数 计算
            tmp.update({
                'id': random.randint(1, 99999999),
                'host_ip': i.get('ip'),
                'cluster_name': "-",
                "cpu_usage": "-",
                "log_level": "-",
                "mem_usage": "-",
                "run_time": "-",
                "service_name": i.get('service_instance_name'),
                "service_port": service_port,
                "service_status": service_status,
                "service_type": "2",
                "basic": [
                    {"name": "port_status", "name_cn": "监听端口",
                     "value": service_ports},
                    {"name": "IP", "name_cn": "IP地址", "value": i.get('ip')},
                ]
            })

        tmp_list.append(tmp) if tmp else '其他组件暂不支持'

    # 扫描统计
    scan_info = {"host": 0, "service": len(services), "component": 0}
    # 分析结果
    scan_result = {
        "all_target_num": tag_total_num,
        "abnormal_target": tag_error_num,
        "healthy": f"{round((tag_error_num / tag_total_num) * 100, 2)}%"
        if tag_total_num > 0 else "100%"
    }
    return scan_info, scan_result, tmp_list

# -*- coding: utf-8 -*-
# Project: new_install_serializers
# Author: jon.liu@yunzhihui.com
# Create time: 2021-11-12 09:23
# IDE: PyCharm
# Version: 1.0
# Introduction:

"""
安装过程中使用的各种序列化类
"""

import json
import logging

from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import Serializer


from db_models.models import (
    ProductHub,
    Service,
    ClusterInfo,
    Product,
    Host,
    ApplicationHub
)

from app_store.new_install_utils import (
    ProductServiceParse,
    SerDependenceParseUtils,
    make_lst_unique,
    SerWithUtils,
    ServiceArgsPortUtils,
    BaseEnvServiceUtils,
    RedisDB,
    BaseRedisData,
    CreateInstallPlan,
    MakeServiceOrder
)

logger = logging.getLogger("server")

UNIQUE_KEY_ERROR = "后台无法追踪此流程,请重新进行安装操作!"


class BaseInstallSerializer(Serializer):
    """ 安装过程中使用的基础序列化类 """
    unique_key = serializers.CharField(
        help_text="操作唯一值",
        required=True,
        error_messages={"required": "必须包含[unique_key]字段"}
    )
    data = serializers.DictField(help_text="详细安装数据可选范围")

    def validate_unique_key(self, unique_key):  # NOQA
        """
        校验整个流程标志是否符合当前流程要求
        :param unique_key: 操作唯一标识
        :type unique_key: str
        :return:
        """
        return BaseRedisData(unique_key).get_unique_key()


class CreateInstallInfoSerializer(BaseInstallSerializer):
    """
    请求格式：
    {
        "high_availability": true,
        "install_product": [
            {
                "name": "jenkinsNB",
                "version": "2.303.2"
            }
        ],
        "unique_key": "abf7d622-6fc8-4a04-ad4c-49b57298ecdf"
    }
    """
    high_availability = serializers.BooleanField(
        write_only=True, required=True,
        help_text="是否选择高可用模式",
        error_messages={"required": "必须包含[high_availability]字段"}
    )
    install_product = serializers.ListField(
        child=serializers.DictField(),
        help_text="产品列表，eg: [{'name': 'ser1', 'version': '1'}]",
        write_only=True, required=True,
        error_messages={"required": "必须包含[install_product]字段"}
    )
    data = serializers.DictField(
        help_text="详细安装数据",
        read_only=True
    )

    def check_product_dependence(self, pro_obj, all_dic):   # NOQA
        """

        :param pro_obj: 应用对象
        :type pro_obj: ProductHub
        :param all_dic: 即将安装应用与版本的对应关系
        :type all_dic: dict
        :return:
        """
        if not pro_obj.pro_dependence or \
                not json.loads(pro_obj.pro_dependence):
            return
        for el in json.loads(pro_obj.pro_dependence):
            _el_name = el["name"]
            _el_version = el["version"]
            # 如果当次安装已包含了依赖应用则跳过
            if _el_name in all_dic and \
                    _el_version == all_dic[_el_name]:
                continue
            # 如果当前系统中存在已安装应用则跳过
            if Product.objects.filter(
                    product__pro_name=_el_name,
                    product__pro_version=_el_version
            ).exists():
                continue
            # 以上都不满足那么需要阻断安装程序
            raise ValidationError(
                f"应用 [{pro_obj.pro_name}] [{pro_obj.pro_version}] "
                f"缺少依赖: [{_el_name}] [{_el_version}]"
            )

    def validate_install_product(self, install_product):  # NOQA
        """
        校验即将安装的产品、应用是否在可支持范围内
        :param install_product: 要安装的应用
        :type install_product: list
        :return:
        """
        # 获取所有要安装产品的name: version映射字典
        _all_dic = {el["name"]: el["version"] for el in install_product}
        for item in install_product:
            _name = item.get("name")
            _version = item.get("version")
            pro_obj = ProductHub.objects.filter(
                pro_name=_name,
                pro_version=_version,
                is_release=True
            ).last()
            if not pro_obj:
                raise ValidationError(f"应用 [{_name}] [{_version}] 不存在")
            self.check_product_dependence(pro_obj, _all_dic)
        return install_product

    def create(self, validated_data):
        """
        构建前端可选安装数据
        :param validated_data:
        :return:
        """
        logger.info(
            f"CreateInstallInfoSerializer.validated_data: {validated_data}")
        install_product = validated_data["install_product"]
        high_availability = validated_data["high_availability"]

        _basic = list()
        # 遍历所有需要安装的产品，将产品下的服务信息收集并存储至_basic变量内
        for item in install_product:
            _pro_info = ProductServiceParse(
                pro_name=item.get("name"),
                pro_version=item.get("version"),
                high_availability=high_availability
            ).run()
            _basic.append(_pro_info)

        # 设置_recheck_service用于过滤服务、组件间重复性数据
        _recheck_service = dict()
        # 遍历所有需要安装的自研服务信息，确定服务的依赖关系并存储至_dependence变量内
        _dependence = list()
        for _pro in _basic:
            for item in _pro.get("services_list"):
                _recheck_service.update({
                    item.get("name", "") + "-" + item.get("version", ""): True
                })
                _dep = SerDependenceParseUtils(
                    parse_name=item.get("name"),
                    parse_version=item.get("version"),
                    high_availability=high_availability
                ).run_ser()
                _dependence.extend(_dep)

        # 使用make_lst_unique方法将服务依赖列表去重处理
        _dependence = make_lst_unique(
            lst=_dependence, key_1="name", key_2="version")
        # 自研服务与基础组件重复处理
        _recheck_dependence = list()
        for item in _dependence:
            _key = item.get("name", "") + "-" + item.get("version", "")
            if _key in _recheck_service:
                continue
            _recheck_dependence.append(item)

        # 判断最终用户可否进行下一步的标记
        is_continue = True
        for item in _basic:
            if "error_msg" in item and item["error_msg"]:
                is_continue = False
                break
        for item in _recheck_dependence:
            if "error_msg" in item and item["error_msg"]:
                is_continue = False
        validated_data["data"] = {
            "basic": _basic,
            "dependence": _recheck_dependence,
            "is_continue": is_continue
        }
        # 存储基础信息到redis
        if is_continue:
            BaseRedisData(
                validated_data["unique_key"]
            ).step_2_set_origin_install_data_args(data=validated_data)
        return validated_data


class CheckInstallInfoSerializer(BaseInstallSerializer):
    """ 安装基础信息校验接口 """

    def get_product_instance_name_lst(self):  # NOQA
        """
        获取集群名称列表
        :return:
        """
        product_ins_name_lst = Product.objects.values("product_instance_name")
        return [el["product_instance_name"] for el in product_ins_name_lst]

    def get_cluster_name_lst(self):  # NOQA
        """
        获取集群名称列表
        :return:
        """
        cluster_name_lst = ClusterInfo.objects.values("cluster_name")
        return [el["cluster_name"] for el in cluster_name_lst]

    def check_basic_product_instance_name_unique(self, lst):
        """
        检查产品集群名称实例是否存在重复，如果安装的是产品，那么必定有产品集群名称
        cluster_name必须存在
        :param lst:
        :return:
        """
        product_instance_name_lst = self.get_product_instance_name_lst()
        is_repeat = False
        for item in lst:
            _name = item.get("name")
            if "cluster_name" not in item:
                is_repeat = True
                item["error_msg"] = f"{_name}实例名称[cluster_name]必须填写"
                continue
            if item["cluster_name"] in product_instance_name_lst:
                is_repeat = True
                item["error_msg"] = \
                    f"产品实例名称: {item['cluster_name']} 不允许重复"
        return is_repeat, lst

    def check_dependence_cluster_name_unique(self, lst):
        """
        检查服务实例名称、集群实例名称是否重复
        :param lst:
        :return:
        """
        cluster_name_lst = self.get_cluster_name_lst()
        is_repeat = False
        for item in lst:
            _name = item.get('name')
            if item.get("deploy_mode") == "single":
                continue
            if item.get("is_base_env") or \
                    item.get("is_use_exist") or \
                    item.get("deploy_mode", 0) == 1:
                continue
            if isinstance(item.get("deploy_mode"), int) and \
                    item.get("deploy_mode", 0) > 1 and \
                    "cluster_name" not in item:
                item["error_msg"] = f"{_name}应用集群实例名称[cluster_name]必须填写"
                is_repeat = True
                continue
            if "cluster_name" not in item:
                item["error_msg"] = f"{_name}应用集群实例名称[cluster_name]必须填写"
                is_repeat = True
                continue
            if item["cluster_name"] in cluster_name_lst:
                is_repeat = True
                item["error_msg"] = \
                    f"{_name}应用集群实例名称: {item['cluster_name']} 不允许重复"
        return is_repeat, lst

    def validate_data(self, data):
        """
        校验请求数据、返回校验结果
        :param data:
        :return:
        """
        basic = data["basic"]
        dependence = data["dependence"]

        basic_repeat, basic = \
            self.check_basic_product_instance_name_unique(lst=basic)
        dependence_repeat, dependence = \
            self.check_dependence_cluster_name_unique(lst=dependence)
        _data = {
            "basic": basic,
            "dependence": dependence
        }
        # TODO 开源组件部署模式校验
        #  使用已存在服务校验
        if basic_repeat or dependence_repeat:
            _data["is_continue"] = False
        else:
            _data["is_continue"] = True
        return _data

    def check_service(self, validated_data, use_exist, install):    # NOQA
        is_continue = True
        for item in validated_data["data"].get("basic", []):
            for el in item.get("services_list"):
                if el.get("name") not in install or \
                        el.get("version") != install[el.get("name")]["version"]:
                    el["error_msg"] = f"无法追踪此服务: {el.get('name')}"
                    is_continue = False
        for item in validated_data["data"].get("use_exist", []):
            if item.get("is_use_exist") and \
                    not use_exist.get(item.get("name")):
                item["error_msg"] = f"此服务不存在: {item.get('name')}, 无法复用"
                is_continue = False
        return is_continue

    def create(self, validated_data):
        """
        :param validated_data:
        :return:
        """
        _re_obj = RedisDB()
        _flag, _data = _re_obj.get(
            name=validated_data["unique_key"] + "_step_2_origin_data"
        )
        if not _flag:
            raise ValidationError(UNIQUE_KEY_ERROR)
        is_continue = validated_data["data"].get("is_continue")
        if is_continue:
            install = _data["install"]
            use_exist = _data["use_exist"]
            is_continue = self.check_service(
                validated_data=validated_data,
                use_exist=use_exist,
                install=install
            )
        if not is_continue:
            validated_data["data"]["is_continue"] = False
        else:
            # 存储安装数据到redis
            BaseRedisData(
                validated_data["unique_key"]
            ).step_3_set_checked_data(data=validated_data)
        return validated_data


class CreateServiceDistributionSerializer(BaseInstallSerializer):
    """ 生成服务分布数据 """
    data = serializers.DictField(
        read_only=True,
        help_text="详细安装数据"
    )

    def get_host_info(self):  # NOQA
        """
        获取主机信息
        :return:
        """
        host_queryset = Host.objects.all().values(
            "ip", "service_num").order_by("-created")
        return [
            {"ip": el["ip"], "num": el["service_num"]} for el in host_queryset
        ]

    def get_basic_data(self, data, all_data, check_data):  # NOQA
        """
        获取产品应用中的服务数量信息
        :param data: 产品basic列表
        :type data: list
        :param all_data: 全部数据字典
        :type all_data: dict
        :param check_data: 已校验过的需要安装的服务的名称及版本信息
        :type check_data: dict
        :return:
        """
        for item in data:
            services_list = item.get("services_list", [])
            for el in services_list:
                all_data[el.get("name")] = {
                    "num": el.get("deploy_mode"),
                    "with": SerWithUtils(
                        ser_name=el.get("name"),
                        ser_version=check_data[el["name"]]["version"]
                    ).run()
                }
        return all_data

    def get_denpendence_data(self, data, all_data, check_data):  # NOQA
        """
        获取依赖信息的服务数量
        :param data: 依赖信息列表
        :type data: list
        :param all_data: 所有服务及数量关系字典
        :type all_data: dict
        :param check_data: 已校验过的需要安装的服务的名称及版本信息
        :type check_data: dict
        :return:
        """
        for item in data:
            if item.get("is_use_exist") or item.get("is_base_env"):
                continue
            if isinstance(item.get("deploy_mode"), int):
                all_data[item.get("name")] = {
                    "num": item.get("deploy_mode"),
                    "with": SerWithUtils(
                        ser_name=item.get("name"),
                        ser_version=check_data[item["name"]]["version"]
                    ).run()
                }
            else:
                # TODO 目前仅支持mysql单节点
                if item.get("name") == "mysql":
                    deploy_num = \
                        1 if item.get("deploy_mode") == "single" else 2
                else:
                    deploy_num = 1
                all_data[item.get("name")] = {
                    "num": deploy_num,
                    "with": SerWithUtils(
                        ser_name=item.get("name"),
                        ser_version=check_data[item["name"]]["version"]
                    ).run()
                }
        return all_data

    def get_product_info(self, data, lst):  # NOQA
        """
        获取应用产品与服务的关系，为后续使用级联选择做准备
        :param data: 产品信息列表
        :type data: list
        :param lst: 返回信息列表
        :type lst: list
        :return:
        """
        for item in data:
            lst.append({
                "name": item.get("name"),
                "child": [
                    el.get("name") for el in item.get("services_list", [])
                ]
            })
        return lst

    def get_basic_info(self, data, lst):  # NOQA
        """
        :param data: 基础组件列表
        :type data: list
        :param lst: 返回信息列表
        :type lst: list
        :return:
        """
        lst.append({
            "name": "基础组件",
            "child": [
                el.get("name") for el in data if not el.get("is_base_env")
            ]
        })
        return lst

    def create(self, validated_data):
        """
        校验
        :param validated_data:
        :return:
        """
        validated_data["data"] = dict()
        validated_data["data"]["host"] = self.get_host_info()
        _re_obj = RedisDB()
        flag, _data = _re_obj.get(
            validated_data["unique_key"] + "_step_3_checked_data")
        if not flag:
            raise ValidationError(UNIQUE_KEY_ERROR)
        check_flag, check_data = _re_obj.get(
            validated_data["unique_key"] + "_step_2_origin_data")
        if not check_flag:
            raise ValidationError(UNIQUE_KEY_ERROR)
        basic = _data.get("data", {}).get("basic", [])
        dependence = _data.get("data", {}).get("dependence", [])
        all_data = dict()
        self.get_basic_data(
            data=basic,
            all_data=all_data,
            check_data=check_data.get("install", {})
        )
        self.get_denpendence_data(
            data=dependence,
            all_data=all_data,
            check_data=check_data.get("install", {})
        )
        validated_data["data"]["all"] = all_data
        product_lst = list()
        self.get_product_info(data=basic, lst=product_lst)
        self.get_basic_info(data=dependence, lst=product_lst)
        validated_data["data"]["product"] = product_lst
        BaseRedisData(
            validated_data['unique_key']
        ).step_4_set_service_distribution(data=all_data)
        return validated_data


class CheckServiceDistributionSerializer(BaseInstallSerializer):
    """ 检查服务分布 """
    is_continue = serializers.BooleanField(
        help_text="可否继续下一步骤操作",
        read_only=True
    )
    error_lst = serializers.ListField(
        help_text="错误信息列表",
        read_only=True
    )

    def validate_data(self, data):  # NOQA
        """
        校验安装数据分布的合法性
        {'10.0.14.234': ['doucApi', 'doucSso']}
        :param data: 服务分布字典
        :type data: dict
        :return:
        """
        logger.info(
            f"CheckServiceDistributionSerializer.validate_data: "
            f"data: {data}")
        # 校验主机及主机上的服务是否存在
        ip_lst = [el["ip"] for el in Host.objects.values("ip")]
        error_lst = list()
        for key, value in data.items():
            if key not in ip_lst:
                error_lst.append({"ip": key, "error_msg": f"无法找到主机{key}"})
                continue
            exist_services = Service.objects.filter(
                ip=key, service__app_name__in=value
            )
            if exist_services.exists():
                _msg = ','.join([el.service.app_name for el in exist_services])
                error_lst.append(
                    {
                        "ip": key,
                        "error_msg": f"主机{key}上存在重复服务: {_msg}"
                    }
                )
        if error_lst:
            data["error_lst"] = error_lst
        return data

    def create(self, validated_data):
        """
        校验
        {
            'unique_key': '886e8fc4-8e77-4de0-8123-9f3aec31ed73',
            'data': {
                '10.0.14.234': ['doucApi', 'doucSso']
            }
        }
        :param validated_data:
        :return:
        """
        logger.info(
            f"CheckServiceDistributionSerializer.create: "
            f"validated_data: {validated_data}")
        if "error_lst" in validated_data["data"] and \
                validated_data["data"]["error_lst"]:
            validated_data["error_lst"] = \
                validated_data["data"].pop("error_lst")
            validated_data["is_continue"] = False
            return validated_data
        # 校验服务数量准确性
        all_install_service = dict()
        for _, value in validated_data["data"].items():
            for item in value:
                if item not in all_install_service:
                    all_install_service[item] = 0
                all_install_service[item] += 1
        _re_obj = RedisDB()
        _flag, _data = _re_obj.get(
            name=f"{validated_data['unique_key']}_step_4_service_distribution")
        if not _flag:
            raise ValidationError(UNIQUE_KEY_ERROR)
        for key, value in _data.items():
            if key not in all_install_service:
                raise ValidationError(f"缺少必须部署的服务{key}")
            if value["num"] != all_install_service[key]:
                raise ValidationError(
                    f"服务{key}应部署{value['num']}个实例，"
                    f"实际部署{all_install_service[key]}个")
        # TODO 服务绑定的准确性校验
        # 临时数据存储至redis
        BaseRedisData(
            validated_data['unique_key']).step_5_set_host_and_service_map(
            host_list=list(validated_data["data"].keys()),
            host_service_map=validated_data["data"]
        )
        return validated_data


class CreateInstallPlanSerializer(BaseInstallSerializer):
    """ 创建安装计划序列化类 """
    is_continue = serializers.BooleanField(
        help_text="可否继续下一步骤操作",
        read_only=True
    )
    error_lst = serializers.ListField(
        help_text="错误信息列表",
        read_only=True
    )
    run_user = serializers.CharField(
        help_text="服务运行用户",
        required=True, allow_null=True, allow_blank=True
    )

    def check_service_dis(self, host_service_map, install_data):  # NOQA
        """
        校验服务分布是否正确
        :param host_service_map: 存储在redis中的服务与主机的对应关系
        :type host_service_map: dict
        :param install_data: 提交上来的服务与主机的对应关系
        :type install_data: dict
        :return:
        """
        error_lst = list()
        for key, value in install_data.items():
            if not host_service_map.get(key):
                error_lst.append({key: "此主机未被选中，请重新查看服务分布策略"})
                continue
            if len(value) == 0:
                continue
            if len(value) != len(host_service_map.get(key)):
                error_lst.append({
                    key: f"此主机服务数量不准确，"
                         f"应选{len(host_service_map.get(key))}; "
                         f"实际为：{len(value)}"
                })
                continue
            for el in value:
                if el.get("name") not in host_service_map.get(key):
                    error_lst.append({key: f"此服务{el.get('name')}不在安装范围内"})
        return error_lst

    def make_final_install_data(
            self, install_data, valid_data,
            run_user, host_ser_map, cluster_name_map
    ):
        """
        构建最终的安装数据
        :param install_data:
        :param valid_data:
        :param run_user:
        :param host_ser_map:
        :param cluster_name_map:
        :return:
        """
        all_install_service_lst = list()
        for ip, ser_lst in install_data.items():
            data_folder = Host.objects.filter(ip=ip).last().data_folder
            if len(ser_lst) != 0:
                for item in ser_lst:
                    item["ip"] = ip
                    item["version"] = valid_data[item["name"]]["version"]
                    item["install_args"] = ServiceArgsPortUtils(
                        ip=ip, data_folder=data_folder, run_user=run_user
                    ).reformat_install_args(item["install_args"])
                    item["data_folder"] = data_folder
                    item["run_user"] = run_user
                    item["cluster_name"] = cluster_name_map.get(item["name"])
                all_install_service_lst.extend(ser_lst)
            else:
                for item in host_ser_map[ip]:
                    _dic = {
                        "name": item,
                        "version": valid_data[item]["version"],
                        "ip": ip
                    }
                    _app = ApplicationHub.objects.filter(
                        app_name=item,
                        app_version=valid_data[item]["version"]
                    ).last()
                    _dic["data_folder"] = data_folder
                    _dic["run_user"] = run_user
                    _dic["install_args"] = \
                        ServiceArgsPortUtils(
                            ip=ip, data_folder=data_folder, run_user=run_user
                    ).remake_install_args(obj=_app)
                    _dic["ports"] = \
                        ServiceArgsPortUtils(
                            ip=ip, data_folder=data_folder, run_user=run_user
                    ).get_app_port(obj=_app)
                    _dic["instance_name"] = \
                        item + "-" + "-".join(ip.split(".")[-2:])
                    _dic["cluster_name"] = cluster_name_map.get(item)
                    all_install_service_lst.append(_dic)
        return all_install_service_lst

    def create(self, validated_data):
        """
        创建部署计划
        :param validated_data:
        :return:
        """
        logger.info(
            f"CreateInstallPlanSerializer.create: "
            f"validated_data: {validated_data}")
        run_user = validated_data["run_user"]
        unique_key = validated_data["unique_key"]
        # 获取存储在redis中的服务与主机的映射关系
        _host_ser_map = BaseRedisData(
            unique_key).get_step_5_host_service_map()
        install_data = validated_data["data"]
        # 校验服务数量及合法性 TODO 后期可针对服务数量准确性进行详细校验
        error_lst = self.check_service_dis(
            host_service_map=_host_ser_map, install_data=install_data)
        if error_lst:
            validated_data["error_lst"] = error_lst
            validated_data["is_continue"] = False
            return validated_data
        cluster_name_map = BaseRedisData(
            unique_key).get_step_3_cluster_name_map()
        # 组装服务数据
        _valid_data = BaseRedisData(
            unique_key).get_step_2_origin_data()
        _install_data = _valid_data["install"]
        # _use_exist_data = _valid_data["use_exist"]
        all_install_service_lst = self.make_final_install_data(
            install_data=install_data,
            valid_data=_install_data,
            run_user=run_user,
            host_ser_map=_host_ser_map,
            cluster_name_map=cluster_name_map
        )
        # 解决base_env服务的安装
        base_env_ser_lst = BaseEnvServiceUtils(
            all_install_service_lst=all_install_service_lst).run()
        all_install_service_lst.extend(base_env_ser_lst)
        logger.info(
            f"Install data:\n"
            f"{json.dumps(all_install_service_lst, indent=2, ensure_ascii=False)}"
        )
        # TODO 生成部署计划 json文件 服务安装排序 依赖关系绑定
        # 服务排序处理
        all_install_service_lst = MakeServiceOrder(
            all_service=all_install_service_lst
        ).run()
        _flag, _res = CreateInstallPlan(
            all_install_service_lst=all_install_service_lst,
            unique_key=unique_key
        ).run()
        if not _flag:
            logger.error(f"Failed CreateInstallPlan: {_res}")
            raise _res
        return validated_data
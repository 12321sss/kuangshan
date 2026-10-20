package com.ganfeng.rs;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 智慧矿山 - 遥感解译与监测预警平台 · 业务服务入口
 * demo 阶段：认证 + 项目/任务/传感器的内存模拟数据，解译功能留白
 */
@SpringBootApplication
public class RsPlatformApplication {

    public static void main(String[] args) {
        SpringApplication.run(RsPlatformApplication.class, args);
    }
}

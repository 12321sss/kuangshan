@echo off
REM ============================================================
REM 智慧矿山平台 - Windows 一键启动脚本
REM 前置：已装好 JDK17 + Maven + Node + Python + MySQL8（详见 README）
REM 启动顺序：MySQL(手动) -> 后端 -> 解译服务 -> 前端
REM ============================================================
setlocal enabledelayedexpansion

echo ==============================================
echo  智慧矿山平台 启动
echo ==============================================
echo.

REM ---- 可配置路径（按目标机器修改）----
set JDK17=C:\Java17\jdk-17.0.2
set MVN=C:\dev\apache-maven-3.9.9\bin\mvn.cmd
set PY=inference\.venv\Scripts\python.exe

REM ---- 1. 构建并启动后端 ----
echo [1/3] 构建并启动后端 (8080)...
cd backend-java
if not exist target\rs-platform-backend-0.0.1-SNAPSHOT.jar (
    echo   首次运行，开始 Maven 构建（需 JDK17）...
    set "JAVA_HOME=%JDK17%"
    call "%MVN%" -s ..\deploy\maven-settings.xml -DskipTests package
    if errorlevel 1 (
        echo   [错误] 后端构建失败，请检查 JDK17/Maven 路径
        pause
        exit /b 1
    )
)
echo   启动后端...
start "rs-backend" "%JDK17%\bin\java.exe" -jar target\rs-platform-backend-0.0.1-SNAPSHOT.jar --server.port=8080
cd ..

REM ---- 2. 启动解译服务 ----
echo [2/3] 启动解译服务 (8010)...
cd inference
if not exist .venv\Scripts\python.exe (
    echo   [提示] 未找到 venv，请先执行：
    echo   python -m venv .venv
    echo   .venv\Scripts\python -m pip install -r requirements.txt
    cd ..
) else (
    start "rs-inference" ".venv\Scripts\python.exe" -m uvicorn main:app --port 8010 --host 127.0.0.1
    cd ..
)

REM ---- 3. 启动前端 ----
echo [3/3] 启动前端 (5173)...
cd frontend
if not exist node_modules (
    echo   首次运行，开始 npm install（Cesium 较大，耐心等）...
    call npm install
)
start "rs-frontend" cmd /c "npm run dev"
cd ..

echo.
echo ==============================================
echo  启动完成！访问地址：
echo    前端   http://localhost:5173
echo    后端   http://localhost:8080/actuator/health
echo    解译   http://localhost:8010/health
echo  账号：admin/admin123
echo.
echo  注意：MySQL 需单独启动（mysqld），库 rs_platform
echo ==============================================
pause

import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect(
        hostname="143.110.167.159",
        username="root",
        password="octagon@88Hexagon"
    )
    
    print("✓ Connected to DigitalOcean droplet")
    
    # Upload bot files
    sftp = ssh.open_sftp()
    sftp.put("/home/ubuntu/mean_reversion_bot.py", "/home/ubuntu/mean_reversion_bot.py")
    sftp.put("/home/ubuntu/telegram_notifier.py", "/home/ubuntu/telegram_notifier.py")
    sftp.put("/home/ubuntu/trade_logger.py", "/home/ubuntu/trade_logger.py")
    sftp.close()
    
    print("✓ Bot files uploaded")
    
    # Create systemd service file for mean-reversion bot
    service_content = """[Unit]
Description=Mean-Reversion Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/ubuntu
ExecStart=/usr/bin/python3 /home/ubuntu/mean_reversion_bot.py
Restart=always
RestartSec=10
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
"""
    
    # Write service file
    stdin, stdout, stderr = ssh.exec_command(f"cat > /etc/systemd/system/mean-reversion.service << 'EOF'\n{service_content}\nEOF")
    stdout.channel.recv_exit_status()
    
    print("✓ Systemd service created")
    
    # Reload systemd and enable service
    stdin, stdout, stderr = ssh.exec_command("systemctl daemon-reload && systemctl enable mean-reversion")
    stdout.channel.recv_exit_status()
    
    print("✓ Service enabled")
    
    # Start the service
    stdin, stdout, stderr = ssh.exec_command("systemctl start mean-reversion")
    stdout.channel.recv_exit_status()
    
    print("✓ Service started")
    
    # Wait and check status
    time.sleep(5)
    
    stdin, stdout, stderr = ssh.exec_command("systemctl status mean-reversion --no-pager -l")
    status_output = stdout.read().decode()
    
    print("\n--- Bot Status ---")
    print(status_output[-800:])
    
    # Check if bot is responding on port 5001
    print("\n--- Testing Bot API ---")
    stdin, stdout, stderr = ssh.exec_command("curl -s http://localhost:5001/health")
    api_response = stdout.read().decode()
    print(f"Health check: {api_response}")
    
    ssh.close()
    print("\n✓ Deployment complete! Bot running on port 5001")
    print("  - London Fortress bot: port 5000 (can be stopped if needed)")
    print("  - Mean-Reversion bot: port 5001 (NEW)")
    
except Exception as e:
    print(f"✗ Deployment failed: {e}")
    import traceback
    traceback.print_exc()
    ssh.close()

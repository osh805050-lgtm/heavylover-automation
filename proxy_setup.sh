#!/bin/bash
# AWS Lightsail (Ubuntu 22.04) 프록시 서버 자동 설정 스크립트
# 사용법: 인스턴스 SSH 접속 후 이 스크립트 전체를 복사해서 붙여넣기

set -e

echo "=== 헤비로버 프록시 서버 설정 시작 ==="

# 1. 시스템 업데이트
sudo apt-get update -y

# 2. Squid 프록시 설치
sudo apt-get install -y squid apache2-utils

# 3. 기본 설정 백업
sudo cp /etc/squid/squid.conf /etc/squid/squid.conf.backup

# 4. 비밀번호 파일 생성 (프록시 인증용)
PROXY_USER="heavylover"
PROXY_PASS=$(openssl rand -base64 16)
echo "$PROXY_USER:$(openssl passwd -apr1 $PROXY_PASS)" | sudo tee /etc/squid/passwords > /dev/null

# 5. Squid 설정 파일 작성
sudo tee /etc/squid/squid.conf > /dev/null <<'EOF'
# 헤비로버 프록시 서버 설정
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwords
auth_param basic realm HeavyLoverProxy
auth_param basic credentialsttl 24 hours

acl authenticated proxy_auth REQUIRED

# 네이버 API 도메인만 허용 (보안)
acl naver_api dstdomain api.commerce.naver.com
acl cafe24_api dstdomain .cafe24api.com
acl naver_image dstdomain .pstatic.net

# 접근 규칙
http_access allow authenticated naver_api
http_access allow authenticated cafe24_api
http_access allow authenticated naver_image
http_access deny all

# 포트 설정
http_port 3128

# 익명 프록시 설정 (클라이언트 IP 숨김)
forwarded_for delete
via off
request_header_access X-Forwarded-For deny all
EOF

# 6. Squid 서비스 재시작
sudo systemctl restart squid
sudo systemctl enable squid

# 7. 방화벽 설정 (3128 포트 열기)
sudo ufw allow 3128/tcp
sudo ufw --force enable

# 8. 결과 출력
echo ""
echo "=== 설정 완료! ==="
echo ""
echo "아래 정보를 Python 코드 .env에 추가하세요:"
echo ""
echo "PROXY_HOST=$(curl -s https://api.ipify.org)"
echo "PROXY_PORT=3128"
echo "PROXY_USER=$PROXY_USER"
echo "PROXY_PASSWORD=$PROXY_PASS"
echo ""
echo "이 프록시 서버의 공인 IP: $(curl -s https://api.ipify.org)"
echo "이 IP를 네이버 API 센터에 등록하세요!"

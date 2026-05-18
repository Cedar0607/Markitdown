第二步：先用独立图片服务，避免碰 Dify

我建议图片服务先跑在 8088 端口，不改 Dify 原有配置。

创建图片目录：

sudo mkdir -p /opt/rag-assets/docs
sudo chmod -R 755 /opt/rag-assets
启动一个专门托管图片的 Nginx 容器：

docker run -d \
  --name rag-assets-nginx \
  --restart unless-stopped \
  -p 8088:80 \
  -v /opt/rag-assets:/usr/share/nginx/html:ro \
  nginx:alpine
测试：

curl -I http://127.0.0.1:8088/
如果返回 200 或 403 都说明 Nginx 活着。403 是因为目录没有首页文件，不影响图片访问。

第三步：确认 Dify 能访问图片服务

假设服务器 IP 是：

10.10.20.15
那么图片 URL 前缀就是：

http://10.10.20.15:8088/docs
注意这里不是 /assets/docs，因为我们把：

/opt/rag-assets
挂到了 Nginx 的网站根目录。

所以文件：

/opt/rag-assets/docs/doc001/image_001.png
访问地址就是：

http://10.10.20.15:8088/docs/doc001/image_001.png
在 Dify 所在服务器或容器里测试：

curl -I http://10.10.20.15:8088/docs/
如果 Dify 就在同一台服务器上，也建议用真实 IP 测，不要只测 127.0.0.1。

第四步：转换脚本参数这样填

你的转换命令里：

--asset-root /opt/rag-assets/docs
--asset-url-base http://10.10.20.15:8088/docs
完整示例：

python /opt/rag-ingest/convert_docx.py /data/docs/test.docx \
  --asset-root /opt/rag-assets/docs \
  --asset-url-base http://10.10.20.15:8088/docs \
  --caption-placeholder
这样生成的 Markdown 会引用：

![图片](http://10.10.20.15:8088/docs/test_xxxxx/image_001_abcd.png)
是否会冲突？

不会，只要端口不同：

Dify nginx:        80 / 443
图片 nginx:        8088
冲突只会发生在你又启动一个 Nginx 去抢 80 或 443。

后面流程跑稳后，你可以再升级成同域名形式，比如：

http://dify.company.local/assets/docs/...
那时再把图片目录挂进 Dify 自带 nginx 或前置反向代理里。第一阶段别动 Dify 的 nginx，先用 8088 独立跑，最容易排错。

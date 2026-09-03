# Architecture & Anti-Ban Security Model

## Why Antigravity Proxy Carries Zero Ban Risk

### 1. The High-Risk Architecture of Public Proxies
Traditional reverse proxies hosted on public cloud VPS introduce massive security and anti-abuse triggers:
1. **Shared Datacenter IPs**: Hundreds of accounts access Google Cloud through the same VPS IP subnet.
2. **Browser Fingerprint Spoofing**: Simulating headless Chrome or reverse-engineering web tokens inevitably leaks inconsistent TLS/JA3/JA4 fingerprints.
3. **Session Interception**: Credentials and cookies travel through external third-party servers.

### 2. Antigravity Proxy's Local Loopback Architecture
Antigravity Proxy functions purely as an in-memory protocol adapter:

```
[Local AI Client] 
      │ (OpenAI HTTP / 127.0.0.1)
      ▼
[Antigravity Proxy:8765]
      │ (Local Subprocess pipe stream-json)
      ▼
[Official agy CLI Engine]
      │ (Google DeepMind Official TLS Handshake)
      ▼
[Google Cloud / Antigravity Backend]
```

- **Loopback Only (`127.0.0.1`)**: Never listens on public interfaces or forwards tokens to external servers.
- **Official CLI Binary**: All network traffic to Google Cloud originates strictly from Google's signed `agy` binary.
- **Authentic Credentials**: Leverages existing, legitimate developer authentication already stored on the machine.
- **5-Way Concurrency Queue**: Bounded semaphore protects against burst-induced HTTP 429 rate-limiting.

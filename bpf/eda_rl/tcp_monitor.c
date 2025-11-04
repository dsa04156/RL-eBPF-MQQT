// tcp_monitor.c — eBPF program for TCP metrics collection
// Tracks RTT, retransmissions, send/recv buffer usage for MQTT flows

#include <linux/version.h>
#include <uapi/linux/ptrace.h>
#include <linux/tcp.h>
#include <linux/skbuff.h>
#include <net/sock.h>
#include <linux/in.h>   // AF_INET

struct key_t {
    __u32 saddr;   // host order
    __u32 daddr;   // host order
    __u16 sport;   // host order
    __u16 dport;   // big-endian
};

struct val_t {
    __u64 retrans;
    __u32 srtt_us;
    __u32 sndbuf;
    __u32 rcvbuf;
};

BPF_HASH(stats, struct key_t, struct val_t, 16384);

static __always_inline int is_mqtt_port_be(__u16 p_be) {
    __u16 p = bpf_ntohs(p_be);
    return p == /*TRACK_PORT*/ __TRACK_PORT__;
}

static __always_inline int fill_key(struct sock *sk, struct key_t *key) {
    // __sk_common을 통해 안전하게 읽기
    struct sock_common *skc = (struct sock_common *)&sk->__sk_common;

    __u16 family = 0;
    bpf_probe_read_kernel(&family, sizeof(family), &skc->skc_family);
    if (family != AF_INET) return 0;

    __u16 sport_host = 0;
    __be16 dport_be  = 0;
    __u32 saddr_host = 0;
    __u32 daddr_host = 0;

    bpf_probe_read_kernel(&sport_host,  sizeof(sport_host),  &skc->skc_num);         // host
    bpf_probe_read_kernel(&dport_be,    sizeof(dport_be),    &skc->skc_dport);       // be16
    bpf_probe_read_kernel(&saddr_host,  sizeof(saddr_host),  &skc->skc_rcv_saddr);   // host
    bpf_probe_read_kernel(&daddr_host,  sizeof(daddr_host),  &skc->skc_daddr);       // host

    if (!(is_mqtt_port_be(bpf_htons(sport_host)) || is_mqtt_port_be(dport_be))) return 0;

    key->saddr = saddr_host;
    key->daddr = daddr_host;
    key->sport = sport_host;  // host order
    key->dport = dport_be;    // big-endian
    return 1;
}

TRACEPOINT_PROBE(tcp, tcp_retransmit_skb) {
    struct sock *sk = (struct sock *)args->skaddr;
    if (!sk) return 0;
    struct key_t k = {};
    if (!fill_key(sk, &k)) return 0;
    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) { __sync_fetch_and_add(&v->retrans, 1); }
    return 0;
}

int on_tcp_sendmsg(struct pt_regs *ctx, struct sock *sk, struct msghdr *msg, size_t size) {
    if (!sk) return 0;
    struct key_t k = {};
    if (!fill_key(sk, &k)) return 0;
    __u32 wmem = 0;
    bpf_probe_read_kernel(&wmem, sizeof(wmem), &sk->sk_wmem_queued);
    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) { v->sndbuf = wmem; }
    return 0;
}

int on_tcp_rcv_established(struct pt_regs *ctx, struct sock *sk) {
    if (!sk) return 0;
    struct key_t k = {};
    if (!fill_key(sk, &k)) return 0;
    struct tcp_sock *tp = (struct tcp_sock *)sk;
    __u32 srtt = 0;
    bpf_probe_read_kernel(&srtt, sizeof(srtt), &tp->srtt_us);
    if (srtt) srtt >>= 3;
    __u32 rmem = 0;
    bpf_probe_read_kernel(&rmem, sizeof(rmem), &sk->sk_rmem_alloc);
    struct val_t zero = {};
    struct val_t *v = stats.lookup_or_init(&k, &zero);
    if (v) { v->srtt_us = srtt; v->rcvbuf = rmem; }
    return 0;
}

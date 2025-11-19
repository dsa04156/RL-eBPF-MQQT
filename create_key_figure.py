#!/usr/bin/env python3
"""
핵심 그림: TCP Buffer Queuing vs 우리 방법
- TCP congestion control 내용 제거
- 재전송률 비교 제거
- 생성 속도 제어의 핵심만 강조
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 11))
fig.suptitle('Why TCP Cannot Prevent Buffer Queuing\nvs Our Application-Layer Rate Control', 
             fontsize=20, fontweight='bold', y=0.96)

# ============================================================================
# 왼쪽: TCP의 한계
# ============================================================================
ax1.set_xlim(0, 10)
ax1.set_ylim(0, 12)
ax1.axis('off')
ax1.set_title('Problem: TCP Controls Transmission Only', 
              fontsize=16, fontweight='bold', color='#d32f2f', pad=20)

# Application
app_box = FancyBboxPatch((1.5, 10), 3, 1.2, boxstyle="round,pad=0.15", 
                          edgecolor='#1976d2', facecolor='#bbdefb', linewidth=3)
ax1.add_patch(app_box)
ax1.text(3, 10.6, 'Publisher App', ha='center', fontsize=14, fontweight='bold', color='#0d47a1')
ax1.text(3, 10.2, 'Generates 200 msg/s', ha='center', fontsize=11, color='#1565c0')

arrow1 = FancyArrowPatch((3, 10), (3, 8.7), arrowstyle='->', 
                         mutation_scale=35, linewidth=4, color='#1976d2')
ax1.add_patch(arrow1)
ax1.text(4.5, 9.3, 'Keeps\ngenerating\n200 msg/s', fontsize=11, color='#1565c0', fontweight='bold',
         bbox=dict(boxstyle='round', facecolor='#e3f2fd', alpha=0.9))

# Buffer (OVERLOADED)
buffer_box = FancyBboxPatch((0.8, 6.8), 4.4, 2, boxstyle="round,pad=0.15",
                             edgecolor='#d32f2f', facecolor='#ffcdd2', linewidth=4)
ax1.add_patch(buffer_box)
ax1.text(3, 8.2, 'TCP Send Buffer', ha='center', fontsize=14, fontweight='bold', color='#b71c1c')
ax1.text(3, 7.7, 'sk_wmem_queued / sndbuf', ha='center', fontsize=10, color='#c62828')
ax1.text(3, 7.3, 'OVERLOADED (90%+)', ha='center', fontsize=13, color='#d32f2f', fontweight='bold',
         bbox=dict(boxstyle='round', facecolor='#ef5350', alpha=0.3))

circle = Circle((6.3, 7.8), 0.5, color='#ff9800', zorder=10)
ax1.add_patch(circle)
ax1.text(6.3, 7.8, '!', ha='center', va='center', fontsize=24, fontweight='bold', color='white')

ax1.annotate('QUEUING\nDELAY', xy=(6.5, 7.8), xytext=(7.5, 8.5),
             fontsize=12, fontweight='bold', color='#d32f2f',
             bbox=dict(boxstyle='round,pad=0.5', facecolor='#ffebee', edgecolor='#d32f2f', linewidth=2),
             arrowprops=dict(arrowstyle='->', lw=2, color='#d32f2f'))

# Network
net_box = FancyBboxPatch((1.5, 4.5), 3, 1.5, boxstyle="round,pad=0.15",
                          edgecolor='#7b1fa2', facecolor='#e1bee7', linewidth=2)
ax1.add_patch(net_box)
ax1.text(3, 5.5, 'Network', ha='center', fontsize=13, fontweight='bold', color='#4a148c')
ax1.text(3, 5, 'Congested', ha='center', fontsize=11, color='#6a1b9a')

arrow2 = FancyArrowPatch((3, 6.8), (3, 6), arrowstyle='->', 
                         mutation_scale=30, linewidth=3, color='#9c27b0', linestyle='--')
ax1.add_patch(arrow2)
ax1.text(4.3, 6.4, 'Slow\ntransmission', fontsize=10, color='#7b1fa2', style='italic')

# Subscriber
sub_box = FancyBboxPatch((1.5, 2.5), 3, 1.2, boxstyle="round,pad=0.15",
                          edgecolor='#388e3c', facecolor='#c8e6c9', linewidth=2)
ax1.add_patch(sub_box)
ax1.text(3, 3.1, 'Subscriber', ha='center', fontsize=13, fontweight='bold', color='#1b5e20')

arrow3 = FancyArrowPatch((3, 4.5), (3, 3.7), arrowstyle='->', 
                         mutation_scale=25, linewidth=2, color='#66bb6a')
ax1.add_patch(arrow3)

# Result
result_box1 = FancyBboxPatch((0.3, 0.5), 5.4, 1.5, boxstyle="round,pad=0.2",
                              edgecolor='#d32f2f', facecolor='#ffcdd2', linewidth=4)
ax1.add_patch(result_box1)
ax1.text(3, 1.5, 'Result:', ha='center', fontsize=12, fontweight='bold', color='#b71c1c')
ax1.text(3, 1, 'P99 Latency: 50.8 seconds', ha='center',
         fontsize=14, fontweight='bold', color='#d32f2f')
ax1.text(3, 0.65, 'User waits 50+ seconds!', ha='center', fontsize=11, color='#c62828')

problem_text = """TCP cannot control:
• Application generation rate
• Buffer accumulation
• Queuing delay

Result: Messages pile up
in buffer → P99 explosion"""
ax1.text(7.3, 3.5, problem_text, fontsize=10.5, 
         bbox=dict(boxstyle='round,pad=0.8', facecolor='#ffebee', 
                  edgecolor='#d32f2f', linewidth=2.5),
         verticalalignment='center', color='#b71c1c', fontweight='bold')

# ============================================================================
# 오른쪽: 우리 방법
# ============================================================================
ax2.set_xlim(0, 10)
ax2.set_ylim(0, 12)
ax2.axis('off')
ax2.set_title('Solution: Control Generation Rate with eBPF+RL', 
              fontsize=16, fontweight='bold', color='#388e3c', pad=20)

# eBPF + RL
ebpf_box = FancyBboxPatch((5.8, 9.5), 3.5, 2, boxstyle="round,pad=0.15",
                           edgecolor='#00796b', facecolor='#b2dfdb', linewidth=3)
ax2.add_patch(ebpf_box)
ax2.text(7.55, 11, 'eBPF Kernel Monitor', ha='center', fontsize=12, fontweight='bold', color='#004d40')
ax2.text(7.55, 10.5, '• RTT monitoring', ha='center', fontsize=10, color='#00695c')
ax2.text(7.55, 10.15, '• snd_ratio (buffer%)', ha='center', fontsize=10, color='#00695c')
ax2.text(7.55, 9.8, '• Retransmission flag', ha='center', fontsize=10, color='#00695c')

rl_box = FancyBboxPatch((5.8, 7), 3.5, 2, boxstyle="round,pad=0.15",
                         edgecolor='#00796b', facecolor='#b2dfdb', linewidth=3)
ax2.add_patch(rl_box)
ax2.text(7.55, 8.5, 'RL Agent', ha='center', fontsize=12, fontweight='bold', color='#004d40')
ax2.text(7.55, 8, 'Detects Risk:', ha='center', fontsize=10, color='#00695c')
ax2.text(7.55, 7.6, 'snd_ratio = 0.9', ha='center', fontsize=10, 
         color='#d32f2f', fontweight='bold')
ax2.text(7.55, 7.25, '→ Reduce rate!', ha='center', fontsize=10, 
         color='#388e3c', fontweight='bold')

arrow_fb1 = FancyArrowPatch((7.55, 9.5), (7.55, 9), arrowstyle='->', 
                           mutation_scale=25, linewidth=2.5, color='#00897b')
ax2.add_patch(arrow_fb1)

arrow_ctrl = FancyArrowPatch((5.8, 8), (4.5, 10.3), arrowstyle='->', 
                              mutation_scale=35, linewidth=4, color='#43a047',
                              linestyle='--', connectionstyle="arc3,rad=.3")
ax2.add_patch(arrow_ctrl)
ax2.text(4.8, 9, 'Control\nSignal', fontsize=11, color='#2e7d32', fontweight='bold',
         bbox=dict(boxstyle='round', facecolor='#c8e6c9', alpha=0.95))

# Application (CONTROLLED)
app_box2 = FancyBboxPatch((1.5, 10), 3, 1.2, boxstyle="round,pad=0.15",
                           edgecolor='#388e3c', facecolor='#c8e6c9', linewidth=4)
ax2.add_patch(app_box2)
ax2.text(3, 10.6, 'Publisher App', ha='center', fontsize=14, fontweight='bold', color='#1b5e20')
ax2.text(3, 10.2, 'Controlled: 100 msg/s', ha='center', fontsize=11, 
         color='#2e7d32', fontweight='bold')

arrow4 = FancyArrowPatch((3, 10), (3, 8.7), arrowstyle='->', 
                         mutation_scale=35, linewidth=4, color='#66bb6a')
ax2.add_patch(arrow4)
ax2.text(1.2, 9.3, 'Reduced to\n100 msg/s', fontsize=11, color='#2e7d32', fontweight='bold',
         bbox=dict(boxstyle='round', facecolor='#e8f5e9', alpha=0.9))

# Buffer (HEALTHY)
buffer_box2 = FancyBboxPatch((0.8, 6.8), 4.4, 2, boxstyle="round,pad=0.15",
                              edgecolor='#388e3c', facecolor='#c8e6c9', linewidth=4)
ax2.add_patch(buffer_box2)
ax2.text(3, 8.2, 'TCP Send Buffer', ha='center', fontsize=14, fontweight='bold', color='#1b5e20')
ax2.text(3, 7.7, 'sk_wmem_queued / sndbuf', ha='center', fontsize=10, color='#2e7d32')
ax2.text(3, 7.3, 'HEALTHY (30%)', ha='center', fontsize=13, color='#388e3c', fontweight='bold',
         bbox=dict(boxstyle='round', facecolor='#81c784', alpha=0.3))

circle2 = Circle((6.3, 7.8), 0.5, color='#4caf50', zorder=10)
ax2.add_patch(circle2)
ax2.text(6.3, 7.8, 'OK', ha='center', va='center', fontsize=11, fontweight='bold', color='white')

ax2.annotate('NO\nQUEUING', xy=(6.5, 7.8), xytext=(7.5, 5.5),
             fontsize=12, fontweight='bold', color='#388e3c',
             bbox=dict(boxstyle='round,pad=0.5', facecolor='#e8f5e9', edgecolor='#388e3c', linewidth=2),
             arrowprops=dict(arrowstyle='->', lw=2, color='#388e3c'))

# Network
net_box2 = FancyBboxPatch((1.5, 4.5), 3, 1.5, boxstyle="round,pad=0.15",
                           edgecolor='#1976d2', facecolor='#bbdefb', linewidth=2)
ax2.add_patch(net_box2)
ax2.text(3, 5.5, 'Network', ha='center', fontsize=13, fontweight='bold', color='#0d47a1')
ax2.text(3, 5, 'Stable Flow', ha='center', fontsize=11, color='#1565c0')

arrow5 = FancyArrowPatch((3, 6.8), (3, 6), arrowstyle='->', 
                         mutation_scale=30, linewidth=3, color='#42a5f5')
ax2.add_patch(arrow5)

# Subscriber
sub_box2 = FancyBboxPatch((1.5, 2.5), 3, 1.2, boxstyle="round,pad=0.15",
                          edgecolor='#388e3c', facecolor='#c8e6c9', linewidth=2)
ax2.add_patch(sub_box2)
ax2.text(3, 3.1, 'Subscriber', ha='center', fontsize=13, fontweight='bold', color='#1b5e20')

arrow6 = FancyArrowPatch((3, 4.5), (3, 3.7), arrowstyle='->', 
                         mutation_scale=25, linewidth=2, color='#66bb6a')
ax2.add_patch(arrow6)

# Result
result_box2 = FancyBboxPatch((0.3, 0.5), 5.4, 1.5, boxstyle="round,pad=0.2",
                              edgecolor='#388e3c', facecolor='#c8e6c9', linewidth=4)
ax2.add_patch(result_box2)
ax2.text(3, 1.5, 'Result:', ha='center', fontsize=12, fontweight='bold', color='#1b5e20')
ax2.text(3, 1, 'P99 Latency: 0.87 seconds', ha='center',
         fontsize=14, fontweight='bold', color='#388e3c')
ax2.text(3, 0.65, '98.3% improvement!', ha='center', fontsize=11, color='#2e7d32')

solution_text = """Our control:
• Generation rate control
• Prevent buffer pressure
• Proactive (before loss)

Result: Buffer stays healthy
→ P99 stable at <1 second"""
ax2.text(7.3, 3.5, solution_text, fontsize=10.5,
         bbox=dict(boxstyle='round,pad=0.8', facecolor='#e8f5e9',
                  edgecolor='#388e3c', linewidth=2.5),
         verticalalignment='center', color='#1b5e20', fontweight='bold')

plt.tight_layout()
plt.savefig('results/tcp_buffer_mechanism.png', dpi=300, bbox_inches='tight')
plt.savefig('results/tcp_buffer_mechanism.pdf', bbox_inches='tight')
print("✅ Created: results/tcp_buffer_mechanism.png")
print("   [핵심] TCP는 전송만 제어, 우리는 생성 속도 제어 → Buffer queuing 사전 방지")

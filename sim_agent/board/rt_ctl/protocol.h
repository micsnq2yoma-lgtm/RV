#ifndef RV_PROTOCOL_H
#define RV_PROTOCOL_H
#include <stdint.h>
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "Protocol v1 requires explicit little-endian conversion on this host"
#endif
typedef struct __attribute__((packed)) {
    char magic[4]; uint32_t seq; double sim_time;
    double q[7], dq[7], gripper; uint32_t flags, last_cmd_seq;
} rv_state;
typedef struct __attribute__((packed)) {
    char magic[4]; uint32_t seq, ack, mode; double q_des[7], gripper_des;
} rv_command;
_Static_assert(sizeof(rv_state) == 144, "RVS1 size");
_Static_assert(sizeof(rv_command) == 80, "RVC1 size");
#endif

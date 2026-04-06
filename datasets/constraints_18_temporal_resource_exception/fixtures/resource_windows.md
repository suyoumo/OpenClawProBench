Window schedule:
- w1 has 1 standard slot and no exception slot.
- w2 has 1 standard slot and 1 exception slot, but the exception slot consumes the shared overflow budget for the whole schedule.
Requests:
- req_a is the highest-priority standard-eligible request for w1.
- req_b asks for an exception in w1, where no exception is available.
- req_c qualifies for the w2 exception slot.
- req_d is standard-eligible in w2 and has lower priority than req_c, but if req_c takes the exception slot, req_d can still fit only if no overflow budget is consumed elsewhere.
- req_e fails the base eligibility check and can never be accepted.
Your task is to maximize accepted priority without violating the shared overflow budget.

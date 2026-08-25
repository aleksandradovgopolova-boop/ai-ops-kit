check_invariant вызывается в реальных producer'ах: preflight.assess(), run_pipeline return, DeliveryReceipt. Нарушение записывается в invariant_breaches (fail-closed, не молчит).

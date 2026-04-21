"""SePay payment integration package (multi-tenant SaaS).

Contains the SePay client helpers (`sepay`) and the session-driven payment
service (`service`). External HTTP is avoided: QR references are built by pure
string construction, and webhook authenticity is verified locally.

Feature: saas-multi-tenant.
"""

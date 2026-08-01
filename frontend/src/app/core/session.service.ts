import { Injectable } from '@angular/core';

/**
 * Cross-tab session state. Every backend call is scoped by an access role, so
 * the role is set once in the header and shared by both the User and Admin
 * tabs rather than re-entered per form.
 */
@Injectable({ providedIn: 'root' })
export class SessionService {
  /** Role whose documents each request may read/write. Bound via ngModel. */
  accessRole = 'public';
}

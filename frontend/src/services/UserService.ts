export interface UserProfile {
  id: string;
  name: string;
  avatarIcon: string;
  role: string;
  badgeColor: string;
  hasPassword?: boolean;
}

const USERS_STORAGE_KEY = 'midnightbuzz_user_profiles';
const ACTIVE_USER_STORAGE_KEY = 'midnightbuzz_active_user_id';

const DEFAULT_USERS: UserProfile[] = [
  {
    id: 'user-sudhanshu',
    name: 'Sudhanshu',
    avatarIcon: '👑',
    role: 'Master Admin / Creator',
    badgeColor: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)'
  },
  {
    id: 'user-guest1',
    name: 'Guest Workspace 1',
    avatarIcon: '👤',
    role: 'Standard User',
    badgeColor: 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%)'
  },
  {
    id: 'user-team',
    name: 'Media Team Member',
    avatarIcon: '🎬',
    role: 'Content Producer',
    badgeColor: 'linear-gradient(135deg, #10b981 0%, #059669 100%)'
  }
];

export class UserService {
  static getAllUsers(): UserProfile[] {
    try {
      const saved = localStorage.getItem(USERS_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          return parsed;
        }
      }
    } catch (e) {
      console.error("Failed to load user profiles:", e);
    }
    return DEFAULT_USERS;
  }

  static saveAllUsers(users: UserProfile[]): void {
    try {
      localStorage.setItem(USERS_STORAGE_KEY, JSON.stringify(users));
    } catch (e) {
      console.error("Failed to save user profiles:", e);
    }
  }

  static syncWithServer(serverUsers: UserProfile[]): void {
    if (!Array.isArray(serverUsers) || serverUsers.length === 0) return;
    UserService.saveAllUsers(serverUsers);
  }

  static getActiveUser(): UserProfile {
    const allUsers = UserService.getAllUsers();
    try {
      const activeId = localStorage.getItem(ACTIVE_USER_STORAGE_KEY);
      if (activeId) {
        const found = allUsers.find(u => u.id === activeId);
        if (found) return found;
      }
    } catch (e) {}
    return allUsers[0] || DEFAULT_USERS[0];
  }

  static setActiveUser(user: UserProfile): void {
    try {
      localStorage.setItem(ACTIVE_USER_STORAGE_KEY, user.id);
      window.dispatchEvent(new CustomEvent('midnightbuzz_user_changed', { detail: user }));
    } catch (e) {
      console.error("Failed to set active user:", e);
    }
  }

  static createNewUser(name: string, role: string, avatarIcon = '👤', id?: string): UserProfile {
    const allUsers = UserService.getAllUsers();
    const newUser: UserProfile = {
      id: id || `user-${Date.now()}`,
      name: name.trim(),
      avatarIcon: avatarIcon,
      role: role.trim() || 'Custom User',
      badgeColor: 'linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)'
    };
    const updated = [...allUsers, newUser];
    UserService.saveAllUsers(updated);
    UserService.setActiveUser(newUser);
    return newUser;
  }
}


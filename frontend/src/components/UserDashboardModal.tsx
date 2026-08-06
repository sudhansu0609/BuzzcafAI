import React, { useState, useEffect } from 'react';
import { UserService, UserProfile } from '../services/UserService';
import { fetchServerUsers, registerUser, loginUser } from '../services/api';
import { Users, UserPlus, Check, X, Shield, Sparkles, Lock, Key } from 'lucide-react';

interface UserDashboardModalProps {
  onClose: () => void;
  onUserChanged: (newUser: UserProfile) => void;
}

export const UserDashboardModal: React.FC<UserDashboardModalProps> = ({ onClose, onUserChanged }) => {
  const [allUsers, setAllUsers] = useState<UserProfile[]>(UserService.getAllUsers());
  const [activeUser, setActiveUser] = useState<UserProfile>(UserService.getActiveUser());
  const [showCreateForm, setShowCreateForm] = useState(false);

  const [newName, setNewName] = useState('');
  const [newRole, setNewRole] = useState('');
  const [newAvatarIcon, setNewAvatarIcon] = useState('👤');
  const [newPassword, setNewPassword] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const AVATAR_ICONS = ['👑', '👤', '🎬', '🚀', '🎨', '💼', '🎧', '🔬'];

  useEffect(() => {
    fetchServerUsers().then((serverUsers) => {
      if (serverUsers && serverUsers.length > 0) {
        UserService.syncWithServer(serverUsers);
        setAllUsers(UserService.getAllUsers());
      }
    }).catch(() => {});
  }, []);

  const handleSelectUser = async (user: UserProfile) => {
    try {
      setErrorMsg(null);
      await loginUser(user.id);
      setActiveUser(user);
      UserService.setActiveUser(user);
      onUserChanged(user);
    } catch (e: any) {
      setErrorMsg(e.message || "Failed to switch user");
    }
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;

    try {
      setErrorMsg(null);
      const res = await registerUser(newName, newRole, newAvatarIcon, newPassword);
      const createdUser: UserProfile = res.user || {
        id: res.user?.id || `user-${Date.now()}`,
        name: newName.trim(),
        avatarIcon: newAvatarIcon,
        role: newRole.trim() || 'Custom User',
        badgeColor: 'linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%)'
      };

      UserService.createNewUser(createdUser.name, createdUser.role, createdUser.avatarIcon, createdUser.id);
      setAllUsers(UserService.getAllUsers());
      setActiveUser(createdUser);
      onUserChanged(createdUser);
      setShowCreateForm(false);
      setNewName('');
      setNewRole('');
      setNewPassword('');
    } catch (err: any) {
      setErrorMsg(err.message || "Failed to create user account");
    }
  };

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(15, 23, 42, 0.65)',
      backdropFilter: 'blur(8px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999,
      padding: '20px'
    }}>
      <div style={{
        background: '#ffffff',
        borderRadius: '24px',
        width: '100%',
        maxWidth: '520px',
        padding: '28px',
        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
        border: '1px solid rgba(226, 232, 240, 0.8)'
      }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '44px', height: '44px', borderRadius: '14px', background: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '22px' }}>
              👤
            </div>
            <div>
              <h3 style={{ fontSize: '18px', fontWeight: 700, color: '#0f172a', margin: 0 }}>Multi-User Workspace Dashboards</h3>
              <p style={{ fontSize: '12px', color: '#64748b', margin: 0 }}>Private custom models & isolated chat histories per user</p>
            </div>
          </div>
          <button onClick={onClose} style={{ background: '#f1f5f9', border: 'none', width: '32px', height: '32px', borderRadius: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
            <X size={18} color="#64748b" />
          </button>
        </div>

        {/* User Account List */}
        <div style={{ marginBottom: '20px' }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '10px' }}>
            Select Active User Account
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '220px', overflowY: 'auto' }}>
            {allUsers.map((user) => {
              const isSelected = activeUser.id === user.id;

              return (
                <div
                  key={user.id}
                  onClick={() => handleSelectUser(user)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px 16px',
                    borderRadius: '16px',
                    background: isSelected ? '#f8fafc' : '#ffffff',
                    border: isSelected ? '2px solid #6366f1' : '1px solid #e2e8f0',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ width: '38px', height: '38px', borderRadius: '12px', background: user.badgeColor, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', color: '#ffffff' }}>
                      {user.avatarIcon}
                    </div>
                    <div>
                      <div style={{ fontSize: '14px', fontWeight: 700, color: '#0f172a' }}>{user.name}</div>
                      <div style={{ fontSize: '11px', color: '#64748b' }}>{user.role}</div>
                    </div>
                  </div>

                  {isSelected && (
                    <div style={{ background: '#6366f1', color: '#ffffff', padding: '4px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Check size={12} /> Active
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Create New User Form Toggle */}
        {!showCreateForm ? (
          <button
            onClick={() => setShowCreateForm(true)}
            style={{
              width: '100%',
              background: '#f8fafc',
              border: '1px dashed #cbd5e1',
              color: '#475569',
              padding: '12px',
              borderRadius: '14px',
              fontWeight: 600,
              fontSize: '13px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              cursor: 'pointer'
            }}
          >
            <UserPlus size={16} /> Create New User Workspace Profile
          </button>
        ) : (
          <form onSubmit={handleCreateUser} style={{ background: '#f8fafc', padding: '16px', borderRadius: '16px', border: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a' }}>Add New User Workspace Profile</div>

            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>Choose Avatar Icon</label>
              <div style={{ display: 'flex', gap: '8px', overflowX: 'auto' }}>
                {AVATAR_ICONS.map((icon) => (
                  <button
                    type="button"
                    key={icon}
                    onClick={() => setNewAvatarIcon(icon)}
                    style={{
                      background: newAvatarIcon === icon ? '#e0e7ff' : '#ffffff',
                      border: newAvatarIcon === icon ? '2px solid #6366f1' : '1px solid #cbd5e1',
                      borderRadius: '10px',
                      padding: '6px 10px',
                      fontSize: '18px',
                      cursor: 'pointer'
                    }}
                  >
                    {icon}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>User / Workspace Name</label>
              <input
                type="text"
                placeholder="e.g. Alice Workspace"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                style={{ width: '100%', padding: '10px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '13px' }}
                required
              />
            </div>

            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>Role / Description</label>
              <input
                type="text"
                placeholder="e.g. Lead Researcher"
                value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                style={{ width: '100%', padding: '10px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '13px' }}
              />
            </div>

            <div>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>Access Password (Optional)</label>
              <input
                type="password"
                placeholder="Set optional password for this profile..."
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                style={{ width: '100%', padding: '10px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '13px' }}
              />
            </div>

            {errorMsg && (
              <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', color: '#dc2626', padding: '8px 12px', borderRadius: '8px', fontSize: '12px' }}>
                {errorMsg}
              </div>
            )}

            <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
              <button
                type="submit"
                style={{ flex: 1, background: '#6366f1', color: '#ffffff', border: 'none', padding: '10px', borderRadius: '10px', fontWeight: 700, fontSize: '13px', cursor: 'pointer' }}
              >
                Create Account & Switch
              </button>
              <button
                type="button"
                onClick={() => setShowCreateForm(false)}
                style={{ background: '#e2e8f0', color: '#475569', border: 'none', padding: '10px 16px', borderRadius: '10px', fontWeight: 600, fontSize: '13px', cursor: 'pointer' }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        <div style={{ marginTop: '20px', padding: '12px', borderRadius: '12px', background: 'rgba(99, 102, 241, 0.08)', border: '1px solid rgba(99, 102, 241, 0.2)', fontSize: '11px', color: '#4f46e5', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Shield size={14} />
          <span>Active User: <strong>{activeUser.name}</strong> ({activeUser.id}). Custom models and voice chats are strictly private to this user!</span>
        </div>
      </div>
    </div>
  );
};
